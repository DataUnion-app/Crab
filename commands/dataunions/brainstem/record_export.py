from dataclasses import dataclass
import hashlib
import hmac
import json
import math
from pathlib import Path
from typing import Any, Dict, List, Optional

from commands.dataunions.brainstem.record_contract import (
    RecordValidationError,
    parse_record,
)


MAX_SOURCE_BYTES = 20 * 1024 * 1024
MAX_INTERVALS_PER_RECORDING = 3_600
MAX_FULL_NIGHT_INTERVALS = 172_800
MIN_REST_DURATION_SECONDS = 300
MIN_FULL_NIGHT_DURATION_SECONDS = 5 * 60 * 60
MAX_FULL_NIGHT_DURATION_SECONDS = 12 * 60 * 60
MIN_FULL_NIGHT_INTERVALS = 9_000
MIN_FULL_NIGHT_VALID_FRACTION = 0.95
MIN_FULL_NIGHT_COVERAGE_RATIO = 0.9
MAX_FULL_NIGHT_COVERAGE_RATIO = 1.1
MAX_RECORDING_DURATION_SECONDS = 86_400
MIN_INTERVALS_PER_RECORDING = 4
MIN_RR_MS = 250
MAX_RR_MS = 2_000


class RecordExportError(RuntimeError):
    def __init__(self, code: str, status_code: int = 422):
        super().__init__(code)
        self.code = code
        self.status_code = status_code


@dataclass(frozen=True)
class RestingRRRecord:
    recording: Dict[str, Any]
    envelope_timestamp: str
    captured_at_utc: Optional[str]
    valid_rr_intervals: int
    source_id: str
    content_hash: str


@dataclass(frozen=True)
class FullNightRRRecord:
    recording: Dict[str, Any]
    envelope_timestamp: str
    captured_at_utc: Optional[str]
    source_id: str
    content_hash: str


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def resolved_source_path(upload_root: Path, owner: str, stored_path: Any) -> Path:
    if not isinstance(stored_path, str) or not stored_path:
        raise RecordExportError("source_path_invalid")
    upload_root = upload_root.resolve()
    root = (upload_root / owner).resolve()
    try:
        root.relative_to(upload_root)
    except ValueError as exc:
        raise RecordExportError("source_owner_path_invalid") from exc
    candidate = Path(stored_path)
    if not candidate.is_absolute():
        candidate = Path.cwd() / candidate
    if candidate.is_symlink():
        raise RecordExportError("source_symlink_rejected")
    try:
        resolved = candidate.resolve(strict=True)
    except OSError as exc:
        raise RecordExportError("source_not_regular_file") from exc
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise RecordExportError("source_path_outside_upload_root") from exc
    if not resolved.is_file():
        raise RecordExportError("source_not_regular_file")
    return resolved


def load_source_record(
    upload_root: Path, owner: str, document: Dict[str, Any]
) -> Dict[str, Any]:
    try:
        path = resolved_source_path(upload_root, owner, document.get("file_path"))
        if path.stat().st_size > MAX_SOURCE_BYTES:
            raise RecordExportError("source_too_large")
        with path.open("rb") as source:
            raw = source.read(MAX_SOURCE_BYTES + 1)
        if len(raw) > MAX_SOURCE_BYTES:
            raise RecordExportError("source_too_large")
        data = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RecordExportError("source_json_invalid") from exc

    expected_hash = document.get("content_hash")
    actual_hash = hashlib.sha256(canonical_json(data)).hexdigest()
    if not isinstance(expected_hash, str) or not hmac.compare_digest(
        expected_hash, actual_hash
    ):
        raise RecordExportError("source_hash_mismatch")
    return data


def _rr_intervals(
    record: Dict[str, Any], maximum: int
) -> tuple[List[float], int]:
    try:
        payload = record["datasource"]["sensor"]["payloads"]["hbr_rr"]
        rows = payload["data"].split(";")
    except (KeyError, TypeError, AttributeError) as exc:
        raise RecordExportError("rr_payload_invalid") from exc

    intervals: List[float] = []
    observed = 0
    for row in rows:
        if not row.strip():
            continue
        columns = [column.strip() for column in row.split(",")]
        for raw_interval in columns[2:]:
            observed += 1
            if not raw_interval:
                continue
            if observed > maximum:
                raise RecordExportError("interval_limit_exceeded", 413)
            try:
                interval = float(raw_interval)
            except ValueError:
                continue
            if not math.isfinite(interval) or not MIN_RR_MS <= interval <= MAX_RR_MS:
                continue
            intervals.append(int(interval) if interval.is_integer() else interval)
    return intervals, observed


def extract_rr_intervals(record: Dict[str, Any]) -> List[float]:
    return _rr_intervals(record, MAX_INTERVALS_PER_RECORDING)[0]


def _source_identity(document: Dict[str, Any]) -> tuple[str, str]:
    source_id = document.get("_id")
    content_hash = document.get("content_hash")
    if not isinstance(source_id, str) or not source_id:
        raise RecordExportError("source_id_invalid")
    if (
        not isinstance(content_hash, str)
        or len(content_hash) != 64
        or any(character not in "0123456789abcdef" for character in content_hash)
    ):
        raise RecordExportError("source_hash_invalid")
    return source_id, content_hash


def resting_rr_record(
    upload_root: Path, owner: str, document: Dict[str, Any]
) -> Optional[RestingRRRecord]:
    record = load_source_record(upload_root, owner, document)
    try:
        summary = parse_record(record)
    except RecordValidationError as exc:
        raise RecordExportError("source_contract_invalid") from exc
    if (
        summary.record_type != "rest"
        or "hbr_rr" not in summary.recognized_payloads
        or summary.duration < MIN_REST_DURATION_SECONDS
        or summary.duration > MAX_RECORDING_DURATION_SECONDS
    ):
        return None
    try:
        intervals = extract_rr_intervals(record)
    except RecordExportError as exc:
        if exc.code == "interval_limit_exceeded":
            raise
        return None
    if len(intervals) < MIN_INTERVALS_PER_RECORDING:
        return None

    source_id, content_hash = _source_identity(document)
    return RestingRRRecord(
        recording={
            "recordingType": "rest",
            "durationSeconds": int(summary.duration),
            "rrIntervalsMs": intervals,
        },
        envelope_timestamp=summary.envelope_timestamp,
        captured_at_utc=summary.captured_at_utc,
        valid_rr_intervals=summary.valid_rr_intervals,
        source_id=source_id,
        content_hash=content_hash,
    )


def full_night_rr_record(
    upload_root: Path,
    owner: str,
    document: Dict[str, Any],
    allowed_use: str = "aggregate_method_compatibility_only",
) -> Optional[FullNightRRRecord]:
    if allowed_use not in {
        "aggregate_method_compatibility_only",
        "private_descriptive_self_only",
    }:
        raise ValueError("unsupported full-night allowed use")
    record = load_source_record(upload_root, owner, document)
    try:
        summary = parse_record(record)
    except RecordValidationError as exc:
        raise RecordExportError("source_contract_invalid") from exc
    if (
        summary.record_type != "sleep"
        or "hbr_rr" not in summary.recognized_payloads
        or not MIN_FULL_NIGHT_DURATION_SECONDS
        <= summary.duration
        <= MAX_FULL_NIGHT_DURATION_SECONDS
    ):
        return None
    try:
        intervals, observed = _rr_intervals(record, MAX_FULL_NIGHT_INTERVALS)
    except RecordExportError as exc:
        if exc.code == "interval_limit_exceeded":
            raise
        return None
    if (
        observed < MIN_FULL_NIGHT_INTERVALS
        or len(intervals) < MIN_FULL_NIGHT_INTERVALS
        or len(intervals) / observed < MIN_FULL_NIGHT_VALID_FRACTION
    ):
        return None
    coverage = sum(intervals) / 1000 / summary.duration
    if not MIN_FULL_NIGHT_COVERAGE_RATIO <= coverage <= MAX_FULL_NIGHT_COVERAGE_RATIO:
        return None
    source_id, content_hash = _source_identity(document)
    return FullNightRRRecord(
        recording={
            "recordingType": "sleep",
            "durationSeconds": int(summary.duration),
            "intervalSemantics": "detector_rr_unclassified",
            "allowedUse": allowed_use,
            "quality": {
                "observedIntervalCount": observed,
                "acceptedIntervalCount": len(intervals),
                "acceptedFraction": round(len(intervals) / observed, 6),
                "durationCoverageRatio": round(coverage, 6),
                "normalToNormalProvenance": "unverified",
                "officialMethodInputCompatible": False,
            },
            "rrIntervalsMs": intervals,
        },
        envelope_timestamp=summary.envelope_timestamp,
        captured_at_utc=summary.captured_at_utc,
        source_id=source_id,
        content_hash=content_hash,
    )
