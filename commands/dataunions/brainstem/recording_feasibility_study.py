from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
from typing import Iterable, Tuple

from commands.dataunions.brainstem.record_contract import CONTRACT_VERSION


STUDY_ID = "brainstem.real-world-recording-feasibility-repeatability"
PROTOCOL_VERSION = "1.0.0"
CONSENT_VERSION = "1.0.0"
ASSIGNMENT_POLICY = "usual-daily-rest-14d/v1"
DATASET_SCHEMA = "brainstem.recording-feasibility-rr/v1"
DATASET_POLICY = "brainstem.recording-feasibility-rr/14d-v1"
ALGORITHM_ID = "brainstem.recording-feasibility-repeatability/v1"
COLLECTION_DAYS = 14
MIN_DURATION_SECONDS = 300
MAX_DURATION_SECONDS = 360
MIN_VALID_RR_INTERVALS = 240
MAX_FUTURE_SKEW_SECONDS = 300
UTC_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
CANDIDATE_PARTICIPANT_INFORMATION = (
    "Candidate generated-data wording only. Joining would allow eligible "
    "Brainstem resting R-R recordings captured during fourteen full UTC study "
    "days, starting at the next UTC day boundary after enrollment, to "
    "contribute to one feasibility study. It would not authorize payment, "
    "diagnosis, treatment, historical-data use, or another study."
)
CONSENT_CONTENT_SHA256 = hashlib.sha256(
    CANDIDATE_PARTICIPANT_INFORMATION.encode("utf-8")
).hexdigest()


class StudyContractError(ValueError):
    pass


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


def candidate_protocol() -> dict:
    """Return the generated-only candidate; human approval is still required."""
    return {
        "status": "candidate-generated-only",
        "studyId": STUDY_ID,
        "protocolVersion": PROTOCOL_VERSION,
        "consentVersion": CONSENT_VERSION,
        "consentContentSha256": CONSENT_CONTENT_SHA256,
        "assignmentPolicy": ASSIGNMENT_POLICY,
        "datasetSchema": DATASET_SCHEMA,
        "datasetPolicy": DATASET_POLICY,
        "algorithmId": ALGORITHM_ID,
        "collectionDays": COLLECTION_DAYS,
        "recordType": "rest",
        "payload": "hbr_rr",
        "minDurationSeconds": MIN_DURATION_SECONDS,
        "maxDurationSeconds": MAX_DURATION_SECONDS,
        "minValidRrIntervals": MIN_VALID_RR_INTERVALS,
        "maxRecordingsPerDay": 1,
        "maxFutureSkewSeconds": MAX_FUTURE_SKEW_SECONDS,
        "studyDayTimezone": "UTC",
        "captureTimeBasis": "verified-device-or-platform-evidence",
        "historicalDataAllowed": False,
        "payment": False,
        "intervention": False,
        "diagnosis": False,
    }


def protocol_sha256() -> str:
    encoded = json.dumps(
        candidate_protocol(), sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _utc(value: datetime, field: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise StudyContractError(f"{field}_invalid")
    return value.astimezone(timezone.utc)


def _stored_utc(value) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.strptime(value, UTC_FORMAT).replace(tzinfo=timezone.utc)
    except ValueError:
        return None
    return parsed if parsed.strftime(UTC_FORMAT) == value else None


def candidate_from_document(
    document, *, capture_time_verified: bool = False
) -> CandidateRecord | None:
    """Adapt explicit-time records only after a trusted provenance check."""
    if (
        capture_time_verified is not True
        or
        not isinstance(document, dict)
        or document.get("file_type") != "record"
        or document.get("record_contract_version") != CONTRACT_VERSION
        or not isinstance(document.get("_id"), str)
        or not document["_id"]
        or not isinstance(document.get("recognized_payloads"), list)
    ):
        return None
    accepted = _stored_utc(document.get("accepted_at_utc"))
    captured = _stored_utc(document.get("captured_at_utc"))
    if accepted is None or captured is None:
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


def assignment_window(enrollment, has_current_data_consent):
    if has_current_data_consent is not True:
        return None
    fixed = {
        "document_type": "brainstem_study_enrollment",
        "study_id": STUDY_ID,
        "protocol_version": PROTOCOL_VERSION,
        "consent_version": CONSENT_VERSION,
        "consent_content_sha256": CONSENT_CONTENT_SHA256,
        "assignment_policy": ASSIGNMENT_POLICY,
        "protocol_sha256": protocol_sha256(),
        "state": "active",
        "withdrawn_at": None,
    }
    if (
        not isinstance(enrollment, dict)
        or any(enrollment.get(key) != value for key, value in fixed.items())
        or not isinstance(enrollment.get("assignment_starts_at"), int)
        or isinstance(enrollment.get("assignment_starts_at"), bool)
        or not isinstance(enrollment.get("assignment_ends_at"), int)
        or isinstance(enrollment.get("assignment_ends_at"), bool)
    ):
        return None
    start = datetime.fromtimestamp(
        enrollment["assignment_starts_at"], timezone.utc
    )
    end = datetime.fromtimestamp(enrollment["assignment_ends_at"], timezone.utc)
    if end - start != timedelta(days=COLLECTION_DAYS):
        raise StudyContractError("assignment_window_invalid")
    return start, end


def qualifying_day(
    record: CandidateRecord,
    enrollment,
    *,
    has_current_data_consent,
) -> int | None:
    """Return the prospective UTC study-day index, or None when ineligible."""
    window = assignment_window(enrollment, has_current_data_consent)
    if window is None:
        return None
    if (
        not isinstance(record, CandidateRecord)
        or not isinstance(record.record_id, str)
        or not record.record_id
    ):
        raise StudyContractError("record_invalid")

    start, end = window
    accepted = _utc(record.accepted_at, "accepted_at")
    captured = _utc(record.captured_at, "captured_at")

    if accepted < start or accepted >= end or captured < start or captured >= end:
        return None
    if captured > accepted + timedelta(seconds=MAX_FUTURE_SKEW_SECONDS):
        return None
    if (
        record.record_type != "rest"
        or not isinstance(record.recognized_payloads, tuple)
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
    records: Iterable[CandidateRecord],
    enrollment,
    *,
    has_current_data_consent,
) -> Tuple[Tuple[int, str], ...]:
    """Select the earliest accepted qualifying record for each study day."""
    eligible = []
    for record in records:
        day = qualifying_day(
            record,
            enrollment,
            has_current_data_consent=has_current_data_consent,
        )
        if day is not None:
            eligible.append((record.accepted_at, record.record_id, day))

    chosen = {}
    for _accepted_at, record_id, day in sorted(eligible):
        chosen.setdefault(day, record_id)
    return tuple(sorted(chosen.items()))
