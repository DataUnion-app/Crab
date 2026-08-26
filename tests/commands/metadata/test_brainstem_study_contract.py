from datetime import datetime, timedelta, timezone

from eth_account import Account
from eth_account.messages import encode_defunct
import pytest

from commands.dataunions.brainstem.study_contract import (
    CandidateRecord,
    StudyContractError,
    candidate_protocol,
    create_survey_revision,
    delete_survey,
    eligibility,
    participant_survey_projection,
    qualifying_day,
    researcher_study_projection,
    select_daily_records,
    survey_contract,
    withdraw_survey,
)
from commands.dataunions.brainstem.study_enrollment import (
    StudyEnrollmentError,
    apply_signed_action,
    create_action_challenge,
    mark_survey_corrected,
)


NOW = 1785595200
ORIGIN = "https://desci.example"
ACCOUNT = Account.from_key("0x" + "11" * 32)
ANSWERS = {
    "adult_status": "yes",
    "chronic_condition_status": "unsure",
    "clinician_confirmation_status": "prefer_not_to_say",
}


def survey(answers=ANSWERS, previous=None, now=NOW):
    return create_survey_revision(
        answers, submitted_at=now, previous=previous
    )


def challenge(action, revision, current=None, now=NOW):
    return create_action_challenge(
        user_id="participant-1",
        address=ACCOUNT.address,
        origin=ORIGIN,
        action=action,
        survey_revision=revision,
        current=current,
        now=now,
        challenge_id_factory=lambda: "1" * 32,
        nonce_factory=lambda: "a" * 43,
    )


def apply(value, revision, current=None, now=NOW + 1):
    signature = Account.sign_message(
        encode_defunct(text=value["message"]), ACCOUNT.key
    ).signature.hex()
    return apply_signed_action(
        value,
        current,
        user_id="participant-1",
        address=ACCOUNT.address,
        origin=ORIGIN,
        action=value["action"],
        signature=signature,
        survey_revision=revision,
        current_data_consent=True,
        now=now,
    )


def test_fixed_candidate_keeps_self_report_out_of_clinical_ground_truth():
    contract = survey_contract()
    protocol = candidate_protocol()

    assert contract["evidenceSource"] == "participant_self_report"
    assert contract["clinicalVerification"] is False
    assert contract["freeTextAllowed"] is False
    assert protocol["status"] == "candidate_generated_only"
    assert protocol["historicalDataAllowed"] is False
    assert protocol["diagnosis"] is False
    assert protocol["durationSeconds"] == [300, 300]


def test_survey_is_exact_bounded_and_contradictions_fail_closed():
    assert eligibility(ANSWERS) == {"status": "eligible", "reason": None}
    refused = dict(ANSWERS, adult_status="prefer_not_to_say")
    assert eligibility(refused)["status"] == "ineligible"
    contradictory = dict(
        ANSWERS,
        chronic_condition_status="no",
        clinician_confirmation_status="yes",
    )
    with pytest.raises(
        StudyContractError, match="survey_answers_contradictory"
    ):
        survey(contradictory)
    with pytest.raises(StudyContractError, match="survey_answers_invalid"):
        survey(dict(ANSWERS, free_text="private note"))


def test_correction_withdrawal_and_deletion_are_immutable_transitions():
    first = survey()
    corrected = survey(
        dict(ANSWERS, chronic_condition_status="yes"),
        previous=first,
        now=NOW + 10,
    )

    assert corrected["revision"] == 2
    assert corrected["supersedes"] == first["revisionSha256"]
    assert first["state"] == "active"
    withdrawn = withdraw_survey(corrected, withdrawn_at=NOW + 20)
    deleted = delete_survey(withdrawn, deleted_at=NOW + 30)
    assert withdrawn["state"] == "withdrawn"
    assert withdrawn["revisionSha256"] == corrected["revisionSha256"]
    assert withdrawn["revisionHashScope"] == "submitted_content/v1"
    assert deleted["state"] == "deleted"
    assert "answers" not in deleted
    assert "answersSha256" not in deleted
    assert "revisionSha256" not in deleted
    assert "supersedes" not in deleted
    assert participant_survey_projection(corrected)["answers"] == corrected[
        "answers"
    ]


def test_researcher_projection_never_contains_answers_or_exact_small_counts():
    projection = researcher_study_projection(
        [{"enrollmentState": "active"} for _ in range(19)]
    )
    assert projection["recruitment"] == "fewer_than_20"
    assert projection["participantAnswersExposed"] is False
    assert set(projection) == {
        "studyId",
        "protocolVersion",
        "surveyVersion",
        "recruitment",
        "participantAnswersExposed",
    }
    assert "19" not in str(projection)


def test_exact_signed_enrollment_binds_survey_and_requires_renewal_after_edit():
    first = survey()
    enrollment_challenge = challenge("enroll", first)
    consumed, enrollment = apply(enrollment_challenge, first)

    assert enrollment["state"] == "active"
    assert enrollment["surveyRevisionSha256"] == first["revisionSha256"]
    assert set(consumed) == {
        "schema",
        "challengeId",
        "action",
        "studyId",
        "issuedAt",
        "expiresAt",
        "consumedAt",
    }

    corrected = survey(
        dict(ANSWERS, chronic_condition_status="yes"),
        previous=first,
        now=NOW + 10,
    )
    renewal = mark_survey_corrected(
        enrollment, corrected["revisionSha256"], changed_at=NOW + 10
    )
    assert renewal["state"] == "renewal_required"

    renewed_challenge = challenge(
        "enroll", corrected, renewal, now=NOW + 20
    )
    _consumed, renewed = apply(
        renewed_challenge, corrected, renewal, now=NOW + 21
    )
    assert renewed["enrollmentRevision"] == 2
    assert renewed["supersedes"] is not None

    withdrawal = challenge("withdraw", corrected, renewed, now=NOW + 30)
    _consumed, withdrawn = apply(
        withdrawal, corrected, renewed, now=NOW + 31
    )
    assert withdrawn["state"] == "withdrawn"
    with pytest.raises(StudyEnrollmentError, match="withdrawal_is_terminal"):
        apply(
            challenge("enroll", corrected, withdrawn, now=NOW + 40),
            corrected,
            withdrawn,
            now=NOW + 41,
        )


def test_prospective_assignment_is_bounded_and_one_record_per_utc_day():
    revision = survey()
    _consumed, enrollment = apply(challenge("enroll", revision), revision)
    start = datetime.fromtimestamp(enrollment["startsAt"], timezone.utc)

    def record(identifier, minutes, day=0):
        return CandidateRecord(
            record_id=identifier,
            accepted_at=start + timedelta(days=day, minutes=minutes + 2),
            captured_at=start + timedelta(days=day, minutes=minutes),
            record_type="rest",
            recognized_payloads=("hbr_rr",),
            duration_seconds=300,
            valid_rr_intervals=240,
            capture_time_verified=True,
        )

    assert qualifying_day(
        record("a", 1), enrollment, current_data_consent=True
    ) == 0
    assert select_daily_records(
        [record("later", 10), record("earlier", 1), record("day-two", 1, 2)],
        enrollment,
        current_data_consent=True,
    ) == ((0, "earlier"), (2, "day-two"))
    assert qualifying_day(
        record("a", 1), enrollment, current_data_consent=False
    ) is None
    too_long = record("long", 1)
    too_long = CandidateRecord(
        **{**too_long.__dict__, "duration_seconds": 301}
    )
    assert qualifying_day(
        too_long, enrollment, current_data_consent=True
    ) is None
