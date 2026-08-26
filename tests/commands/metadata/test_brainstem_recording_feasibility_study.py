from datetime import datetime, timedelta, timezone

import pytest

from commands.dataunions.brainstem.recording_feasibility_study import (
    ASSIGNMENT_POLICY,
    CandidateRecord,
    CONSENT_CONTENT_SHA256,
    CONSENT_VERSION,
    PROTOCOL_VERSION,
    STUDY_ID,
    StudyContractError,
    candidate_from_document,
    candidate_protocol,
    protocol_sha256,
    qualifying_day,
    select_daily_records,
)


START = datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc)
ASSIGNMENT_START = datetime(2026, 8, 2, 0, 0, tzinfo=timezone.utc)


def enrollment(state="active"):
    return {
        "document_type": "brainstem_study_enrollment",
        "study_id": STUDY_ID,
        "protocol_version": PROTOCOL_VERSION,
        "protocol_sha256": protocol_sha256(),
        "consent_version": CONSENT_VERSION,
        "consent_content_sha256": CONSENT_CONTENT_SHA256,
        "assignment_policy": ASSIGNMENT_POLICY,
        "state": state,
        "assignment_starts_at": int(ASSIGNMENT_START.timestamp()),
        "assignment_ends_at": int(
            (ASSIGNMENT_START + timedelta(days=14)).timestamp()
        ),
        "withdrawn_at": None if state == "active" else int(START.timestamp()),
    }


def record(
    record_id="record-a",
    *,
    accepted_at=ASSIGNMENT_START + timedelta(minutes=6),
    captured_at=ASSIGNMENT_START + timedelta(minutes=1),
    record_type="rest",
    payloads=("hbr_rr",),
    duration=300,
    valid_rr_intervals=240,
    capture_time_verified=True,
):
    return CandidateRecord(
        record_id=record_id,
        accepted_at=accepted_at,
        captured_at=captured_at,
        record_type=record_type,
        recognized_payloads=payloads,
        duration_seconds=duration,
        valid_rr_intervals=valid_rr_intervals,
        capture_time_verified=capture_time_verified,
    )


def test_candidate_protocol_is_fixed_and_explicitly_not_activated():
    protocol = candidate_protocol()

    assert protocol["status"] == "candidate-generated-only"
    assert protocol["studyId"] == (
        "brainstem.real-world-recording-feasibility-repeatability"
    )
    assert protocol["collectionDays"] == 14
    assert protocol["recordType"] == "rest"
    assert protocol["payload"] == "hbr_rr"
    assert protocol["studyDayTimezone"] == "UTC"
    assert (
        protocol["captureTimeBasis"]
        == "verified-device-or-platform-evidence"
    )
    assert protocol["minValidRrIntervals"] == 240
    assert protocol["historicalDataAllowed"] is False
    assert protocol["payment"] is False
    assert protocol["intervention"] is False
    assert protocol["diagnosis"] is False


def test_only_explicit_server_and_mobile_utc_times_reach_study_binding():
    document = {
        "_id": "record-a",
        "file_type": "record",
        "record_contract_version": "brainstem-record-v1",
        "record_type": "rest",
        "recognized_payloads": ["hbr_rr"],
        "duration": 300,
        "valid_rr_intervals": 240,
        "accepted_at_utc": "2026-08-02T00:06:00Z",
        "captured_at_utc": "2026-08-02T00:01:00Z",
        "t0": 807278460,
    }

    assert candidate_from_document(document) is None
    candidate = candidate_from_document(document, capture_time_verified=True)

    assert candidate is not None
    assert candidate.captured_at == ASSIGNMENT_START + timedelta(minutes=1)
    assert qualifying_day(
        candidate, enrollment(), has_current_data_consent=True
    ) == 0

    for missing in ("accepted_at_utc", "captured_at_utc"):
        legacy = dict(document)
        legacy.pop(missing)
        assert (
            candidate_from_document(legacy, capture_time_verified=True) is None
        )

    for field in ("accepted_at_utc", "captured_at_utc"):
        noncanonical = dict(document)
        noncanonical[field] = "2026-8-2T0:01:00Z"
        assert (
            candidate_from_document(
                noncanonical, capture_time_verified=True
            )
            is None
        )


def test_post_enrollment_record_maps_to_utc_study_day():
    assert qualifying_day(
        record(), enrollment(), has_current_data_consent=True
    ) == 0
    assert qualifying_day(
        record(
            accepted_at=ASSIGNMENT_START + timedelta(days=4, minutes=6),
            captured_at=ASSIGNMENT_START + timedelta(days=4, minutes=1),
        ),
        enrollment(),
        has_current_data_consent=True,
    ) == 4


def test_study_days_change_at_utc_midnight_not_24_hours_after_enrollment():
    assert qualifying_day(
        record(
            accepted_at=datetime(2026, 8, 2, 23, 59, tzinfo=timezone.utc),
            captured_at=datetime(2026, 8, 2, 23, 58, tzinfo=timezone.utc),
        ),
        enrollment(),
        has_current_data_consent=True,
    ) == 0
    assert qualifying_day(
        record(
            accepted_at=datetime(2026, 8, 3, 0, 2, tzinfo=timezone.utc),
            captured_at=datetime(2026, 8, 3, 0, 1, tzinfo=timezone.utc),
        ),
        enrollment(),
        has_current_data_consent=True,
    ) == 1


@pytest.mark.parametrize(
    "candidate",
    [
        record(
            accepted_at=ASSIGNMENT_START - timedelta(seconds=1),
            captured_at=ASSIGNMENT_START + timedelta(seconds=1),
        ),
        record(
            accepted_at=ASSIGNMENT_START + timedelta(minutes=1),
            captured_at=ASSIGNMENT_START - timedelta(seconds=1),
        ),
        record(
            accepted_at=datetime(2026, 8, 16, tzinfo=timezone.utc),
            captured_at=datetime(2026, 8, 15, 23, 59, tzinfo=timezone.utc),
        ),
        record(
            accepted_at=datetime(2026, 8, 15, 23, 59, tzinfo=timezone.utc),
            captured_at=datetime(2026, 8, 16, tzinfo=timezone.utc),
        ),
    ],
)
def test_assignment_window_is_half_open_and_requires_both_timestamps(candidate):
    assert (
        qualifying_day(
            candidate, enrollment(), has_current_data_consent=True
        )
        is None
    )


def test_historical_capture_uploaded_after_enrollment_is_excluded():
    candidate = record(
        accepted_at=ASSIGNMENT_START + timedelta(days=1),
        captured_at=ASSIGNMENT_START - timedelta(days=30),
    )

    assert (
        qualifying_day(
            candidate, enrollment(), has_current_data_consent=True
        )
        is None
    )


def test_future_clock_skew_is_bounded():
    assert qualifying_day(
        record(
            accepted_at=ASSIGNMENT_START + timedelta(minutes=1),
            captured_at=ASSIGNMENT_START + timedelta(minutes=6),
        ),
        enrollment(),
        has_current_data_consent=True,
    ) == 0
    assert qualifying_day(
        record(
            accepted_at=ASSIGNMENT_START + timedelta(minutes=1),
            captured_at=ASSIGNMENT_START + timedelta(minutes=6, seconds=1),
        ),
        enrollment(),
        has_current_data_consent=True,
    ) is None


@pytest.mark.parametrize(
    "candidate",
    [
        record(record_type="normal"),
        record(payloads=("acc_rare",)),
        record(payloads="hbr_rr"),
        record(payloads=None),
        record(duration=299),
        record(duration=361),
        record(duration=float("nan")),
        record(valid_rr_intervals=239),
        record(capture_time_verified=False),
    ],
)
def test_record_content_must_match_the_fixed_candidate_policy(candidate):
    assert (
        qualifying_day(
            candidate, enrollment(), has_current_data_consent=True
        )
        is None
    )


def test_withdrawal_consent_revocation_and_version_mismatch_fail_closed():
    assert (
        qualifying_day(
            record(), enrollment("withdrawn"), has_current_data_consent=True
        )
        is None
    )
    assert (
        qualifying_day(
            record(), enrollment(), has_current_data_consent=False
        )
        is None
    )
    wrong_version = enrollment()
    wrong_version["protocol_version"] = "2.0.0"
    assert (
        qualifying_day(
            record(), wrong_version, has_current_data_consent=True
        )
        is None
    )


def test_naive_record_times_fail_closed():
    with pytest.raises(StudyContractError, match="captured_at_invalid"):
        qualifying_day(
            record(captured_at=ASSIGNMENT_START.replace(tzinfo=None)),
            enrollment(),
            has_current_data_consent=True,
        )


def test_first_accepted_record_per_day_is_selected_deterministically():
    later = record(
        "record-z",
        accepted_at=ASSIGNMENT_START + timedelta(minutes=10),
        captured_at=ASSIGNMENT_START + timedelta(minutes=2),
    )
    earlier = record(
        "record-b",
        accepted_at=ASSIGNMENT_START + timedelta(minutes=5),
        captured_at=ASSIGNMENT_START + timedelta(minutes=3),
    )
    day_two = record(
        "record-c",
        accepted_at=ASSIGNMENT_START + timedelta(days=2, minutes=5),
        captured_at=ASSIGNMENT_START + timedelta(days=2, minutes=1),
    )

    assert select_daily_records(
        [later, day_two, earlier],
        enrollment(),
        has_current_data_consent=True,
    ) == (
        (0, "record-b"),
        (2, "record-c"),
    )
