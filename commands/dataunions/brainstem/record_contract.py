from dataclasses import dataclass
from datetime import datetime, timezone
import math
from typing import Any, Dict, Iterable, Optional, Tuple


CONTRACT_VERSION = "brainstem-record-v1"
KNOWN_RECORD_TYPES = {"normal", "rest", "sleep", "posture", "exercise"}
KNOWN_PAYLOADS = {"hbr_rr", "acc_rare", "acc_frequent", "ecg"}
PAYLOAD_FORMATS = {
    "hbr_rr": "csv",
    "acc_rare": "csv",
    "acc_frequent": "structured",
    "ecg": "structured",
}
TIMESTAMP_FORMAT = "%Y-%m-%d_%H%M%S"
CAPTURE_TIME_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
CAPTURE_TIME_BASIS = "rfc3339-utc"
MIN_RR_MILLISECONDS = 250
MAX_RR_MILLISECONDS = 2000


class RecordValidationError(ValueError):
    pass


@dataclass(frozen=True)
class RecordSummary:
    record_type: str
    envelope_timestamp: str
    captured_at_utc: Optional[str]
    t0: float
    duration: float
    rows: int
    valid_rr_intervals: int
    recognized_payloads: Tuple[str, ...]
    reward_eligible: bool
    reward_kind: Optional[str]
    reward_task_type: Optional[str]
    reward_amount: int
    reward_reason: str

    def as_dict(self) -> Dict[str, Any]:
        return {
            "record_type": self.record_type,
            "envelope_timestamp": self.envelope_timestamp,
            "captured_at_utc": self.captured_at_utc,
            "t0": self.t0,
            "duration": self.duration,
            "rows": self.rows,
            "valid_rr_intervals": self.valid_rr_intervals,
            "recognized_payloads": list(self.recognized_payloads),
            "reward_eligible": self.reward_eligible,
            "reward_kind": self.reward_kind,
            "reward_task_type": self.reward_task_type,
            "reward_amount": self.reward_amount,
            "reward_reason": self.reward_reason,
        }


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise RecordValidationError(message)


def _parse_timestamp(value: Any, field: str) -> float:
    _require(isinstance(value, str), f"{field} must be a timestamp string")
    try:
        parsed = datetime.strptime(value, TIMESTAMP_FORMAT)
    except ValueError as exc:
        raise RecordValidationError(
            f"{field} must match yyyy-MM-dd_HHmmss"
        ) from exc
    _require(
        parsed.strftime(TIMESTAMP_FORMAT) == value,
        f"{field} must match yyyy-MM-dd_HHmmss",
    )
    return parsed.timestamp()


def _capture_time(value: Any) -> Optional[str]:
    if value is None:
        return None
    _require(isinstance(value, dict), "captureTime must be an object")
    _require(
        set(value) == {"basis", "startedAt"},
        "captureTime must contain only basis and startedAt",
    )
    _require(
        value.get("basis") == CAPTURE_TIME_BASIS,
        "captureTime.basis must equal rfc3339-utc",
    )
    started_at = value.get("startedAt")
    _require(
        isinstance(started_at, str),
        "captureTime.startedAt must be a timestamp string",
    )
    try:
        parsed = datetime.strptime(started_at, CAPTURE_TIME_FORMAT).replace(
            tzinfo=timezone.utc
        )
    except ValueError as exc:
        raise RecordValidationError(
            "captureTime.startedAt must match yyyy-MM-ddTHH:mm:ssZ"
        ) from exc
    _require(
        parsed.strftime(CAPTURE_TIME_FORMAT) == started_at,
        "captureTime.startedAt must match yyyy-MM-ddTHH:mm:ssZ",
    )
    return started_at


def _delimited_rows(value: Any, field: str) -> Tuple[float, float, int, int]:
    _require(isinstance(value, str), f"{field}.data must be a string")
    rows = [row.strip() for row in value.split(";") if row.strip()]
    _require(rows, f"{field}.data must contain at least one row")
    timestamps = []
    valid_rr_intervals = 0
    for row in rows:
        values = [item.strip() for item in row.split(",")]
        try:
            timestamps.append(float(values[0]))
            if field == "hbr_rr":
                _require(
                    len(values) >= 2,
                    "hbr_rr.data rows must contain timestamp and heart rate",
                )
                float(values[1])
                for raw in values[2:]:
                    try:
                        interval = float(raw)
                    except ValueError:
                        continue
                    valid_rr_intervals += int(
                        math.isfinite(interval)
                        and MIN_RR_MILLISECONDS <= interval <= MAX_RR_MILLISECONDS
                    )
        except ValueError as exc:
            raise RecordValidationError(
                f"{field}.data rows must contain numeric values"
            ) from exc
    start = min(timestamps)
    end = max(timestamps)
    return start, max(0.0, end - start + 1), len(rows), valid_rr_intervals


def _reading_count(readings: Any, field: str) -> int:
    if isinstance(readings, list):
        _require(readings, f"{field}.data.readings must not be empty")
        return len(readings)
    _require(isinstance(readings, str), f"{field}.data.readings must be a string or list")
    values = [value.strip() for value in readings.split(",") if value.strip()]
    _require(values, f"{field}.data.readings must not be empty")
    return len(values)


def _structured_rows(value: Any, field: str) -> Tuple[float, float, int]:
    _require(isinstance(value, dict), f"{field}.data must be an object")
    start = _parse_timestamp(value.get("t0"), f"{field}.data.t0")
    frequency = value.get("frequency")
    _require(
        isinstance(frequency, (int, float)) and not isinstance(frequency, bool),
        f"{field}.data.frequency must be a number",
    )
    _require(frequency > 0, f"{field}.data.frequency must be greater than zero")
    count = _reading_count(value.get("readings"), field)
    return start, count / float(frequency), count


def _reward_decision(record_type: str, duration: float, rows: int):
    if rows <= 0 or duration <= 0:
        return False, None, None, 0, "no recognized measurable content"
    if record_type not in KNOWN_RECORD_TYPES:
        return False, None, None, 0, "unknown record type"
    if record_type == "rest":
        return True, "rest", "BRA_COMP_REST", 1, "eligible rest record"
    if record_type == "sleep":
        if duration >= 5 * 60 * 60:
            return True, "sleep", "BRA_COMP_SLEEP", 2, "eligible sleep record"
        return False, "sleep", None, 0, "sleep duration below five hours"
    if record_type == "exercise":
        if duration >= 10 * 60:
            return True, "exercise", "BRA_COMP_BREATH_L", 3, "eligible long exercise record"
        if duration >= 5 * 60:
            return True, "exercise", "BRA_COMP_BREATH_S", 2, "eligible exercise record"
        return False, "exercise", None, 0, "exercise duration below five minutes"
    return False, record_type, None, 0, "record type is not rewarded"


def parse_record(data: Any) -> RecordSummary:
    """Validate the stable Brainstem envelope while allowing extension fields."""
    _require(isinstance(data, dict), "record must be a JSON object")
    _require(isinstance(data.get("schemaVersion"), str), "schemaVersion is required")
    record_type = data.get("type")
    _require(isinstance(record_type, str) and record_type, "type is required")
    envelope_timestamp = data.get("timestamp")
    _parse_timestamp(envelope_timestamp, "timestamp")
    captured_at_utc = _capture_time(data.get("captureTime"))

    metadata = data.get("metadata")
    if metadata is not None:
        _require(isinstance(metadata, dict), "metadata must be an object")
        for field in ("gender", "year", "region"):
            _require(field in metadata, f"metadata.{field} is required")
        _require(isinstance(metadata["gender"], str), "metadata.gender must be a string")
        _require(
            isinstance(metadata["year"], (int, float)) and not isinstance(metadata["year"], bool),
            "metadata.year must be a number",
        )
        _require(isinstance(metadata["region"], str), "metadata.region must be a string")

    datasource = data.get("datasource")
    _require(isinstance(datasource, dict), "datasource is required")
    sensor = datasource.get("sensor")
    _require(isinstance(sensor, dict), "datasource.sensor is required")
    _require(isinstance(sensor.get("name"), str), "datasource.sensor.name is required")
    _require(isinstance(sensor.get("id"), str), "datasource.sensor.id is required")
    payloads = sensor.get("payloads")
    _require(isinstance(payloads, dict) and payloads, "datasource.sensor.payloads is required")

    starts = []
    durations = []
    rows = 0
    valid_rr_intervals = 0
    recognized = []
    for name, payload in payloads.items():
        if name not in KNOWN_PAYLOADS:
            continue
        _require(isinstance(payload, dict), f"{name} must be an object")
        _require(payload.get("dataType") == name, f"{name}.dataType must equal {name}")
        _require(
            payload.get("format") == PAYLOAD_FORMATS[name],
            f"{name}.format must equal {PAYLOAD_FORMATS[name]}",
        )
        if name in {"hbr_rr", "acc_rare"}:
            start, duration, count, rr_count = _delimited_rows(
                payload.get("data"), name
            )
            valid_rr_intervals += rr_count
        else:
            start, duration, count = _structured_rows(payload.get("data"), name)
        recognized.append(name)
        starts.append(start)
        durations.append(duration)
        rows += count

    duration = max(durations, default=0.0)
    t0 = min(starts, default=0.0)
    eligible, kind, task, amount, reason = _reward_decision(record_type, duration, rows)
    if not recognized:
        reason = "no recognized payloads"

    return RecordSummary(
        record_type=record_type,
        envelope_timestamp=envelope_timestamp,
        captured_at_utc=captured_at_utc,
        t0=t0,
        duration=duration,
        rows=rows,
        valid_rr_intervals=valid_rr_intervals,
        recognized_payloads=tuple(sorted(recognized)),
        reward_eligible=eligible,
        reward_kind=kind,
        reward_task_type=task,
        reward_amount=amount,
        reward_reason=reason,
    )
