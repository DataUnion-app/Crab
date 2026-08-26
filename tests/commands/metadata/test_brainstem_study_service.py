from copy import deepcopy

import pytest
from eth_account import Account
from eth_account.messages import encode_defunct

from commands.dataunions.brainstem.study_service import BrainstemStudyService
from commands.dataunions.brainstem.study_service import StudyServiceError


NOW = 1785595200
ORIGIN = "https://desci.example"
ACCOUNT = Account.from_key("0x" + "22" * 32)
ANSWERS = {
    "adult_status": "yes",
    "chronic_condition_status": "unsure",
    "clinician_confirmation_status": "prefer_not_to_say",
}


class Auth:
    def authenticate(self, token, origin):
        assert token == "session"
        assert origin == ORIGIN
        return (
            "session-id",
            {},
            {
                "_id": "participant-1",
                "public_address": ACCOUNT.address,
                "usage_flag": "ACCEPTED",
                "guidelines_acceptance_flag": "ACCEPTED",
            },
        )


class Dao:
    def __init__(self):
        self.state = None

    def get_state(self, user_id):
        assert user_id == "participant-1"
        return deepcopy(self.state)

    def mutate_state(self, user_id, mutator):
        value = deepcopy(
            self.state
            or {
                "document_type": "brainstem_study_participant_state",
                "user_id": user_id,
            }
        )
        self.state = mutator(value)
        return deepcopy(self.state)

    def researcher_projection_states(self):
        return [deepcopy(self.state)] if self.state else []


def sign(message):
    return Account.sign_message(
        encode_defunct(text=message), ACCOUNT.key
    ).signature.hex()


def save_survey(service, body):
    challenge = service.challenge("session", ORIGIN, "survey", body)
    return service.apply(
        "session",
        ORIGIN,
        challenge["challengeId"],
        sign(challenge["message"]),
        body,
    )


def test_session_survey_signed_enrollment_correction_and_safe_projection():
    dao = Dao()
    service = BrainstemStudyService(Auth(), dao, clock=lambda: NOW)
    survey = save_survey(
        service, {"surveyVersion": "1.0.0", "answers": ANSWERS}
    )
    assert survey["evidenceSource"] == "participant_self_report"
    assert survey["eligibility"]["status"] == "eligible"

    challenge = service.challenge("session", ORIGIN, "enroll")
    enrolled = service.apply(
        "session", ORIGIN, challenge["challengeId"], sign(challenge["message"])
    )
    assert enrolled == {"status": "active", "enrollmentRevision": 1}

    corrected = dict(ANSWERS, chronic_condition_status="yes")
    save_survey(
        service, {"surveyVersion": "1.0.0", "answers": corrected}
    )
    assert (
        dao.state["survey_history"][0]["revisionSha256"]
        == dao.state["survey"]["supersedes"]
    )
    status = service.status("session", ORIGIN)
    assert status["enrollment"]["state"] == "renewal_required"
    assert status["survey"]["revision"] == 2

    public = service.researcher_status()
    assert public["participantAnswersExposed"] is False
    assert "answers" not in public


def test_invalid_survey_answers_are_a_client_error():
    service = BrainstemStudyService(Auth(), Dao(), clock=lambda: NOW)

    with pytest.raises(StudyServiceError) as error:
        service.challenge(
            "session",
            ORIGIN,
            "survey",
            {
                "surveyVersion": "1.0.0",
                "answers": {
                    **ANSWERS,
                    "chronic_condition_status": "no",
                    "clinician_confirmation_status": "yes",
                },
            },
        )

    assert error.value.status_code == 422
    assert error.value.code == "survey_answers_contradictory"


def test_survey_signature_survives_a_clock_tick_between_build_steps():
    dao = Dao()
    values = iter((NOW, NOW + 1))
    service = BrainstemStudyService(Auth(), dao, clock=lambda: next(values))
    body = {"surveyVersion": "1.0.0", "answers": ANSWERS}

    challenge = service.challenge("session", ORIGIN, "survey", body)
    survey = service.apply(
        "session",
        ORIGIN,
        challenge["challengeId"],
        sign(challenge["message"]),
        body,
    )

    assert survey["eligibility"]["status"] == "eligible"
    assert "surveyRevisionSha256" not in dao.state["last_action"]


def test_withdrawal_stops_future_collection_without_erasing_study_evidence():
    dao = Dao()
    service = BrainstemStudyService(Auth(), dao, clock=lambda: NOW)
    save_survey(service, {"surveyVersion": "1.0.0", "answers": ANSWERS})
    enroll = service.challenge("session", ORIGIN, "enroll")
    service.apply(
        "session", ORIGIN, enroll["challengeId"], sign(enroll["message"])
    )
    withdrawal = service.challenge("session", ORIGIN, "withdraw")
    service.apply(
        "session",
        ORIGIN,
        withdrawal["challengeId"],
        sign(withdrawal["message"]),
    )

    assert dao.state["enrollment"]["state"] == "withdrawn"
    assert dao.state["survey"]["answers"] == ANSWERS
