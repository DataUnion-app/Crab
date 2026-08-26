import pytest

from commands.dataunions.brainstem.record_contract import (
    RecordValidationError,
    parse_record,
)


def record(record_type="rest", payloads=None):
    return {
        "schemaVersion": "1.0",
        "type": record_type,
        "timestamp": "2026-07-17_120000",
        "appVersion": "future-extension",
        "metadata": {
            "gender": "female",
            "year": 1990,
            "region": "Europe",
            "project": "extension",
        },
        "datasource": {
            "sensor": {
                "name": "HW807",
                "id": "device",
                "firmware": "extension",
                "payloads": payloads or {
                    "hbr_rr": {
                        "dataType": "hbr_rr",
                        "format": "csv",
                        "data": "100,60;101,61;102,62",
                        "metrics": {"future": 1},
                    }
                },
            }
        },
        "future": {"is": "preserved by the stored file"},
    }


def test_extra_fields_are_accepted_and_known_content_is_rewarded():
    summary = parse_record(record())

    assert summary.record_type == "rest"
    assert summary.rows == 3
    assert summary.duration == 3
    assert summary.recognized_payloads == ("hbr_rr",)
    assert summary.reward_eligible is True
    assert summary.reward_amount == 1


def test_explicit_utc_capture_time_and_rr_count_support_prospective_studies():
    candidate = record()
    candidate["captureTime"] = {
        "basis": "rfc3339-utc",
        "startedAt": "2026-07-17T12:00:00Z",
    }
    candidate["datasource"]["sensor"]["payloads"]["hbr_rr"]["data"] = (
        "100,60,1000,249;101,61,2500,2501"
    )

    summary = parse_record(candidate)
    assert summary.captured_at_utc == "2026-07-17T12:00:00Z"
    assert summary.valid_rr_intervals == 1


@pytest.mark.parametrize(
    "capture_time",
    [
        "2026-07-17T12:00:00Z",
        {"basis": "apple-reference-2001", "startedAt": "795000000"},
        {"basis": "rfc3339-utc", "startedAt": "2026-07-17T14:00:00+02:00"},
        {"basis": "rfc3339-utc", "startedAt": "2026-7-17T2:00:00Z"},
        {
            "basis": "rfc3339-utc",
            "startedAt": "2026-07-17T12:00:00Z",
            "extra": True,
        },
    ],
)
def test_ambiguous_capture_time_extensions_are_rejected(capture_time):
    candidate = record()
    candidate["captureTime"] = capture_time

    with pytest.raises(RecordValidationError):
        parse_record(candidate)


def test_noncanonical_envelope_timestamp_is_rejected():
    candidate = record()
    candidate["timestamp"] = "2026-7-17_120000"

    with pytest.raises(RecordValidationError):
        parse_record(candidate)


def test_non_numeric_hbr_rr_values_are_rejected():
    candidate = record()
    candidate["datasource"]["sensor"]["payloads"]["hbr_rr"]["data"] = (
        "100,60,1000;101,not-a-heart-rate,900"
    )

    with pytest.raises(RecordValidationError):
        parse_record(candidate)


def test_unknown_payload_is_accepted_but_not_rewarded():
    summary = parse_record(record(payloads={
        "future_sensor": {"dataType": "future", "data": {"anything": True}}
    }))

    assert summary.rows == 0
    assert summary.recognized_payloads == ()
    assert summary.reward_eligible is False
    assert summary.reward_reason == "no recognized payloads"


def test_acc_frequent_counts_values_not_string_characters():
    summary = parse_record(record(payloads={
        "acc_frequent": {
            "dataType": "acc_frequent",
            "format": "structured",
            "data": {
                "t0": "2026-07-17_120000",
                "frequency": 2,
                "readings": "1.0,2.0,3.0,4.0",
            },
        }
    }))

    assert summary.rows == 4
    assert summary.duration == 2


def test_android_array_readings_are_accepted():
    summary = parse_record(record(payloads={
        "ecg": {
            "dataType": "ecg",
            "format": "structured",
            "data": {
                "t0": "2026-07-17_120000",
                "frequency": 4,
                "readings": [1, 2, 3, 4],
            },
        }
    }))

    assert summary.rows == 4
    assert summary.duration == 1


@pytest.mark.parametrize(
    "payload",
    [
        {
            "dataType": "future_type",
            "format": "structured",
            "data": {"t0": "2026-07-17_120000", "frequency": 1, "readings": [1]},
        },
        {
            "dataType": "ecg",
            "format": "csv",
            "data": {"t0": "2026-07-17_120000", "frequency": 1, "readings": [1]},
        },
    ],
)
def test_known_payload_labels_must_match_their_contract(payload):
    with pytest.raises(RecordValidationError):
        parse_record(record(payloads={"ecg": payload}))


@pytest.mark.parametrize("frequency", [0, -1, None])
def test_invalid_frequency_is_rejected(frequency):
    with pytest.raises(RecordValidationError):
        parse_record(record(payloads={
            "ecg": {
                "dataType": "ecg",
                "format": "structured",
                "data": {
                    "t0": "2026-07-17_120000",
                    "frequency": frequency,
                    "readings": [1, 2],
                },
            }
        }))


@pytest.mark.parametrize(
    ("seconds", "eligible", "amount"),
    [(299, False, 0), (300, True, 2), (599, True, 2), (600, True, 3)],
)
def test_exercise_reward_boundaries(seconds, eligible, amount):
    readings = list(range(seconds))
    summary = parse_record(record("exercise", payloads={
        "ecg": {
            "dataType": "ecg",
            "format": "structured",
            "data": {
                "t0": "2026-07-17_120000",
                "frequency": 1,
                "readings": readings,
            },
        }
    }))

    assert summary.reward_eligible is eligible
    assert summary.reward_amount == amount
