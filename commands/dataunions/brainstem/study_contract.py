from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
from typing import Iterable, Tuple

from commands.dataunions.brainstem.record_contract import CONTRACT_VERSION
from commands.dataunions.brainstem.study_fixtures import (
    RECORDING_FEASIBILITY_ID,
)


STUDY_ID = RECORDING_FEASIBILITY_ID
PROTOCOL_VERSION = "1.0.0"
SURVEY_VERSION = "1.0.0"
CONSENT_VERSION = "1.0.0"
ASSIGNMENT_VERSION = "usual-daily-rest-14d/v1"
DATASET_SCHEMA = "brainstem.recording-feasibility-rr/v1"
DATASET_POLICY = "brainstem.recording-feasibility-rr/14d-v1"
ALGORITHM_ID = "brainstem.recording-feasibility-repeatability/v1"
EVIDENCE_SOURCE = "participant_self_report"
REVISION_HASH_SCOPE = "submitted_content/v1"
COLLECTION_DAYS = 14
MIN_DURATION_SECONDS = 300
MAX_DURATION_SECONDS = 300
MIN_VALID_RR_INTERVALS = 240
MAX_FUTURE_SKEW_SECONDS = 300
UTC_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
ANSWERS = {"yes", "no", "unsure", "prefer_not_to_say"}
QUESTIONS = (
    {
        "id": "adult_status",
        "text": "Are you 18 years old or older?",
        "answers": ("yes", "no", "prefer_not_to_say"),
    },
    {
        "id": "chronic_condition_status",
        "text": "Do you live with one or more long-term health conditions?",
        "answers": tuple(sorted(ANSWERS)),
    },
    {
        "id": "clinician_confirmation_status",
        "text": (
            "Has a qualified clinician told you that you have a long-term "
            "health condition?"
        ),
        "answers": tuple(sorted(ANSWERS)),
    },
)
PARTICIPANT_INFORMATION = (
    "Candidate wording for generated testing only. Joining would allow "
    "eligible Brainstem resting R-R recordings made during fourteen full UTC "
    "study days to contribute to one feasibility study. Survey answers are "
    "self-reported and are not a diagnosis or clinically verified ground "
    "truth. Joining does not authorize payment, treatment, historical-data "
    "use, or another study."
)


class StudyContractError(ValueError):
    pass


def _canonical(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def _sha256(value) -> str:
    return hashlib.sha256(
        value.encode() if isinstance(value, str) else _canonical(value)
    ).hexdigest()


def _revision_sha256(value) -> str:
    keys = (
        "schema",
        "studyId",
        "surveyVersion",
        "surveySha256",
        "revision",
        "revisionHashScope",
        "evidenceSource",
        "answers",
        "answersSha256",
        "eligibility",
        "submittedAt",
        "supersedes",
    )
    return _sha256({key: value[key] for key in keys})


def survey_contract() -> dict:
    return {
        "schema": "brainstem.study-survey/v1",
        "studyId": STUDY_ID,
        "surveyVersion": SURVEY_VERSION,
        "evidenceSource": EVIDENCE_SOURCE,
        "questions": [
            {
                "id": question["id"],
                "text": question["text"],
                "answers": list(question["answers"]),
            }
            for question in QUESTIONS
        ],
        "freeTextAllowed": False,
        "clinicalVerification": False,
        "participantInformationStatus": "candidate_generated_only",
    }


def survey_sha256() -> str:
    return _sha256(survey_contract())


def consent_sha256() -> str:
    return _sha256(PARTICIPANT_INFORMATION)


def candidate_protocol() -> dict:
    return {
        "status": "candidate_generated_only",
        "studyId": STUDY_ID,
        "protocolVersion": PROTOCOL_VERSION,
        "surveyVersion": SURVEY_VERSION,
        "surveySha256": survey_sha256(),
        "consentVersion": CONSENT_VERSION,
        "consentSha256": consent_sha256(),
        "assignmentVersion": ASSIGNMENT_VERSION,
        "datasetSchema": DATASET_SCHEMA,
        "datasetPolicy": DATASET_POLICY,
        "algorithmId": ALGORITHM_ID,
        "collectionDays": COLLECTION_DAYS,
        "recordType": "rest",
        "payload": "hbr_rr",
        "durationSeconds": [MIN_DURATION_SECONDS, MAX_DURATION_SECONDS],
        "minimumValidRrIntervals": MIN_VALID_RR_INTERVALS,
        "maximumRecordingsPerDay": 1,
        "maximumFutureSkewSeconds": MAX_FUTURE_SKEW_SECONDS,
        "studyDayTimezone": "UTC",
        "captureTimeBasis": "verified_device_or_platform_evidence",
        "historicalDataAllowed": False,
        "payment": False,
        "intervention": False,
        "diagnosis": False,
    }


def protocol_sha256() -> str:
    return _sha256(candidate_protocol())


def validate_answers(value) -> dict:
    expected = {question["id"]: set(question["answers"]) for question in QUESTIONS}
    if not isinstance(value, dict) or set(value) != set(expected):
        raise StudyContractError("survey_answers_invalid")
    if any(answer not in expected[key] for key, answer in value.items()):
        raise StudyContractError("survey_answers_invalid")
    if (
        value["chronic_condition_status"] == "no"
        and value["clinician_confirmation_status"] == "yes"
    ):
        raise StudyContractError("survey_answers_contradictory")
    return {key: value[key] for key in sorted(value)}


def eligibility(answers) -> dict:
    answers = validate_answers(answers)
    adult = answers["adult_status"]
    if adult == "no":
        return {"status": "ineligible", "reason": "adult_requirement_not_met"}
    if adult == "prefer_not_to_say":
        return {"status": "ineligible", "reason": "adult_status_not_confirmed"}
    return {"status": "eligible", "reason": None}


def create_survey_revision(answers, *, submitted_at, previous=None) -> dict:
    answers = validate_answers(answers)
    if not isinstance(submitted_at, int) or isinstance(submitted_at, bool):
        raise StudyContractError("survey_time_invalid")
    if previous is None:
        revision = 1
        supersedes = None
    else:
        _validate_survey_revision(previous)
        if previous["state"] != "active":
            raise StudyContractError("survey_revision_unavailable")
        if previous["answersSha256"] == _sha256(answers):
            return previous
        revision = previous["revision"] + 1
        supersedes = previous["revisionSha256"]
    document = {
        "schema": "brainstem.study-survey-evidence/v1",
        "studyId": STUDY_ID,
        "surveyVersion": SURVEY_VERSION,
        "surveySha256": survey_sha256(),
        "revision": revision,
        "revisionHashScope": REVISION_HASH_SCOPE,
        "state": "active",
        "evidenceSource": EVIDENCE_SOURCE,
        "answers": answers,
        "answersSha256": _sha256(answers),
        "eligibility": eligibility(answers),
        "submittedAt": submitted_at,
        "supersedes": supersedes,
        "withdrawnAt": None,
        "deletedAt": None,
    }
    document["revisionSha256"] = _revision_sha256(document)
    return document


def supersede_survey(revision) -> dict:
    _validate_survey_revision(revision)
    if revision["state"] != "active":
        raise StudyContractError("survey_revision_unavailable")
    result = dict(revision)
    result["state"] = "superseded"
    return result


def withdraw_survey(revision, *, withdrawn_at) -> dict:
    _validate_survey_revision(revision)
    if revision["state"] == "withdrawn":
        return revision
    if revision["state"] != "active":
        raise StudyContractError("survey_revision_unavailable")
    if not isinstance(withdrawn_at, int) or isinstance(withdrawn_at, bool):
        raise StudyContractError("survey_time_invalid")
    result = dict(revision)
    result["state"] = "withdrawn"
    result["withdrawnAt"] = withdrawn_at
    return result


def delete_survey(revision, *, deleted_at) -> dict:
    _validate_survey_revision(revision)
    if revision["state"] == "deleted":
        return revision
    if not isinstance(deleted_at, int) or isinstance(deleted_at, bool):
        raise StudyContractError("survey_time_invalid")
    return {
        "schema": revision["schema"],
        "studyId": revision["studyId"],
        "surveyVersion": revision["surveyVersion"],
        "surveySha256": revision["surveySha256"],
        "revision": revision["revision"],
        "revisionHashScope": revision["revisionHashScope"],
        "state": "deleted",
        "evidenceSource": revision["evidenceSource"],
        "submittedAt": revision["submittedAt"],
        "deletedAt": deleted_at,
    }


def _validate_survey_revision(value) -> None:
    if (
        not isinstance(value, dict)
        or value.get("schema") != "brainstem.study-survey-evidence/v1"
        or value.get("studyId") != STUDY_ID
        or value.get("surveyVersion") != SURVEY_VERSION
        or value.get("surveySha256") != survey_sha256()
        or value.get("evidenceSource") != EVIDENCE_SOURCE
        or value.get("revisionHashScope") != REVISION_HASH_SCOPE
        or value.get("state")
        not in {"active", "superseded", "withdrawn", "deleted"}
        or not isinstance(value.get("revision"), int)
        or isinstance(value.get("revision"), bool)
        or value["revision"] < 1
    ):
        raise StudyContractError("survey_revision_invalid")
    if value["state"] == "deleted":
        if set(value) != {
            "schema",
            "studyId",
            "surveyVersion",
            "surveySha256",
            "revision",
            "revisionHashScope",
            "state",
            "evidenceSource",
            "submittedAt",
            "deletedAt",
        }:
            raise StudyContractError("survey_revision_invalid")
    elif (
        not isinstance(value.get("revisionSha256"), str)
        or len(value["revisionSha256"]) != 64
        or not isinstance(value.get("answersSha256"), str)
        or len(value["answersSha256"]) != 64
    ):
        raise StudyContractError("survey_revision_invalid")
    else:
        answers = validate_answers(value.get("answers"))
        try:
            revision_sha256 = _revision_sha256(value)
        except (KeyError, TypeError):
            raise StudyContractError("survey_revision_invalid")
        if (
            value["answersSha256"] != _sha256(answers)
            or value.get("eligibility") != eligibility(answers)
            or value["revisionSha256"] != revision_sha256
        ):
            raise StudyContractError("survey_revision_invalid")


def participant_survey_projection(revision) -> dict:
    _validate_survey_revision(revision)
    return {
        "surveyVersion": revision["surveyVersion"],
        "revision": revision["revision"],
        "state": revision["state"],
        "evidenceSource": revision["evidenceSource"],
        "answers": revision.get("answers"),
        "eligibility": revision.get("eligibility"),
    }


def researcher_study_projection(states: Iterable[dict]) -> dict:
    values = list(states)
    active = sum(
        1
        for value in values
        if isinstance(value, dict) and value.get("enrollmentState") == "active"
    )
    # Exact small counts are deliberately suppressed.
    return {
        "studyId": STUDY_ID,
        "protocolVersion": PROTOCOL_VERSION,
        "surveyVersion": SURVEY_VERSION,
        "recruitment": "20_or_more" if active >= 20 else "fewer_than_20",
        "participantAnswersExposed": False,
    }


@dataclass(frozen=True)
class CandidateRecord:
    record_id: str
    accepted_at: datetime
    captured_at: datetime
    record_type: str
    recognized_payloads: Tuple[str, ...]
    duration_seconds: float
    valid_rr_intervals: int
    capture_time_verified: bool


def candidate_from_document(
    document, *, capture_time_verified: bool = False
) -> CandidateRecord | None:
    if (
        capture_time_verified is not True
        or not isinstance(document, dict)
        or document.get("file_type") != "record"
        or document.get("record_contract_version") != CONTRACT_VERSION
        or not isinstance(document.get("_id"), str)
        or not document["_id"]
        or not isinstance(document.get("recognized_payloads"), list)
    ):
        return None
    try:
        accepted = datetime.strptime(
            document["accepted_at_utc"], UTC_FORMAT
        ).replace(tzinfo=timezone.utc)
        captured = datetime.strptime(
            document["captured_at_utc"], UTC_FORMAT
        ).replace(tzinfo=timezone.utc)
    except (KeyError, TypeError, ValueError):
        return None
    if (
        accepted.strftime(UTC_FORMAT) != document["accepted_at_utc"]
        or captured.strftime(UTC_FORMAT) != document["captured_at_utc"]
    ):
        return None
    return CandidateRecord(
        record_id=document["_id"],
        accepted_at=accepted,
        captured_at=captured,
        record_type=document.get("record_type"),
        recognized_payloads=tuple(document["recognized_payloads"]),
        duration_seconds=document.get("duration"),
        valid_rr_intervals=document.get("valid_rr_intervals"),
        capture_time_verified=True,
    )


def assignment_window(enrollment, current_data_consent):
    fixed = {
        "studyId": STUDY_ID,
        "protocolVersion": PROTOCOL_VERSION,
        "protocolSha256": protocol_sha256(),
        "surveyVersion": SURVEY_VERSION,
        "surveySha256": survey_sha256(),
        "consentVersion": CONSENT_VERSION,
        "consentSha256": consent_sha256(),
        "assignmentVersion": ASSIGNMENT_VERSION,
        "state": "active",
    }
    if (
        current_data_consent is not True
        or not isinstance(enrollment, dict)
        or any(enrollment.get(key) != value for key, value in fixed.items())
        or not isinstance(enrollment.get("startsAt"), int)
        or isinstance(enrollment.get("startsAt"), bool)
        or not isinstance(enrollment.get("endsAt"), int)
        or isinstance(enrollment.get("endsAt"), bool)
    ):
        return None
    start = datetime.fromtimestamp(enrollment["startsAt"], timezone.utc)
    end = datetime.fromtimestamp(enrollment["endsAt"], timezone.utc)
    if end - start != timedelta(days=COLLECTION_DAYS):
        raise StudyContractError("assignment_window_invalid")
    return start, end


def qualifying_day(record, enrollment, *, current_data_consent) -> int | None:
    window = assignment_window(enrollment, current_data_consent)
    if window is None:
        return None
    start, end = window
    if (
        not isinstance(record, CandidateRecord)
        or record.accepted_at.tzinfo is None
        or record.captured_at.tzinfo is None
    ):
        raise StudyContractError("record_invalid")
    accepted = record.accepted_at.astimezone(timezone.utc)
    captured = record.captured_at.astimezone(timezone.utc)
    if not (start <= accepted < end and start <= captured < end):
        return None
    if captured > accepted + timedelta(seconds=MAX_FUTURE_SKEW_SECONDS):
        return None
    if (
        record.record_type != "rest"
        or "hbr_rr" not in record.recognized_payloads
        or not isinstance(record.duration_seconds, (int, float))
        or isinstance(record.duration_seconds, bool)
        or not math.isfinite(record.duration_seconds)
        or not MIN_DURATION_SECONDS
        <= record.duration_seconds
        <= MAX_DURATION_SECONDS
        or not isinstance(record.valid_rr_intervals, int)
        or isinstance(record.valid_rr_intervals, bool)
        or record.valid_rr_intervals < MIN_VALID_RR_INTERVALS
        or record.capture_time_verified is not True
    ):
        return None
    return (captured.date() - start.date()).days


def select_daily_records(
    records: Iterable[CandidateRecord], enrollment, *, current_data_consent
) -> Tuple[Tuple[int, str], ...]:
    eligible = []
    for record in records:
        day = qualifying_day(
            record, enrollment, current_data_consent=current_data_consent
        )
        if day is not None:
            eligible.append((record.accepted_at, record.record_id, day))
    chosen = {}
    for _accepted, record_id, day in sorted(eligible):
        chosen.setdefault(day, record_id)
    return tuple(sorted(chosen.items()))
