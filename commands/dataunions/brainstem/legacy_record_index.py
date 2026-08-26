"""Validate retained sleep records and attach purpose-bound legacy provenance."""

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any, Dict

from commands.dataunions.brainstem.consent import has_brainstem_data_consent
from commands.dataunions.brainstem.record_contract import (
    CONTRACT_VERSION,
    RecordValidationError,
    parse_record,
)
from commands.dataunions.brainstem.record_export import (
    MAX_SOURCE_BYTES,
    RecordExportError,
    canonical_json,
    resolved_source_path,
)
from models.GuidelinesAcceptanceFlag import GuidelinesAcceptanceFlag
from models.UsageFlag import UsageFlag


PROVENANCE_SCHEMA = "brainstem.legacy-app-gated-consent/v1"
PROVENANCE_FIELD = "research_consent_provenance"
STUDY_ID = "brainstem.apdet-retrospective-study"
APP_GATE_CUTOFF = "2024-10-10T03:35:12Z"
DECISION = {
    "schema": PROVENANCE_SCHEMA,
    "scope": STUDY_ID,
    "basis": "controller-attested-app-gated-upload",
    "appGateCutoff": APP_GATE_CUTOFF,
    "iosConsentCommit": "1bae1aa73196025b7b99e9805f78519dc2b9f9b5",
    "iosUploadGateCommit": "04700162ff5dcc0616b7f1e90164beccaea0aa1c",
}
DECISION_SHA256 = hashlib.sha256(canonical_json(DECISION)).hexdigest()


class LegacyRecordIndexError(RuntimeError):
    pass


def _timestamp(value: Any) -> datetime:
    if not isinstance(value, str) or not value:
        raise LegacyRecordIndexError("record_created_at_invalid")
    try:
        parsed = datetime.fromisoformat(
            value.replace("UTC", "+00:00").replace("Z", "+00:00")
        )
    except ValueError as exc:
        raise LegacyRecordIndexError("record_created_at_invalid") from exc
    # Legacy Crab wrote datetime.utcnow().isoformat() without an offset.
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _formatted(value: datetime) -> str:
    return value.isoformat(timespec="seconds").replace("+00:00", "Z")


def legacy_consent_marker() -> Dict[str, str]:
    return {
        "schema": PROVENANCE_SCHEMA,
        "scope": STUDY_ID,
        "basis": DECISION["basis"],
        "decisionSha256": DECISION_SHA256,
    }


def legacy_record_consent_marker(uploaded_at: datetime) -> Dict[str, str]:
    return {
        **legacy_consent_marker(),
        "uploadedAtUtc": _formatted(uploaded_at),
    }


def retrospective_research_consent_basis(user: Any) -> str | None:
    if not isinstance(user, dict) or user.get("is_access_blocked") is True:
        return None
    if (
        user.get("usage_flag") == UsageFlag.REJECTED.name
        or user.get("guidelines_acceptance_flag")
        == GuidelinesAcceptanceFlag.REJECTED.name
    ):
        return None
    if has_brainstem_data_consent(user):
        return "current_server_consent"
    return (
        "legacy_app_gated_consent"
        if user.get(PROVENANCE_FIELD) == legacy_consent_marker()
        else None
    )


def has_retrospective_research_consent(user: Any) -> bool:
    return retrospective_research_consent_basis(user) is not None


def record_has_legacy_consent(document: Any) -> bool:
    if not isinstance(document, dict):
        return False
    marker = document.get(PROVENANCE_FIELD)
    if not isinstance(marker, dict):
        return False
    uploaded_at = marker.get("uploadedAtUtc")
    try:
        parsed = _timestamp(uploaded_at)
        return marker == legacy_record_consent_marker(parsed) and parsed >= _timestamp(
            APP_GATE_CUTOFF
        )
    except LegacyRecordIndexError:
        return False


class LegacySleepRecordIndexer:
    def __init__(self, metadata_dao, users_dao, upload_root: Path):
        self.metadata_dao = metadata_dao
        self.users_dao = users_dao
        self.upload_root = Path(upload_root)

    def _documents(self):
        query = {
            "selector": {
                "file_type": "record",
                "source": "brainstem",
                "record_type": "sleep",
            },
            "fields": [
                "_id",
                "created_by",
                "created_at",
                "file_path",
                "file_type",
                "source",
                "record_type",
                "record_contract_version",
                "t0",
                "duration",
                "rows",
                "valid_rr_intervals",
                "recognized_payloads",
                "content_hash",
                "accepted_at_utc",
                "captured_at_utc",
                "metadata",
                PROVENANCE_FIELD,
            ],
        }
        yield from self.metadata_dao.iter_query(query, batch_size=200)

    def _user(self, owner, cache):
        if owner not in cache:
            users = self.users_dao.get_by_public_address(owner).get("result", [])
            cache[owner] = users[0] if len(users) == 1 else None
        return cache[owner]

    def _updates(self, document):
        owner = document.get("created_by")
        created_at = _timestamp(document.get("created_at"))
        if created_at < _timestamp(APP_GATE_CUTOFF):
            raise LegacyRecordIndexError("record_before_app_gate")
        try:
            path = resolved_source_path(
                self.upload_root, owner, document.get("file_path")
            )
            if path.stat().st_size > MAX_SOURCE_BYTES:
                raise LegacyRecordIndexError("source_too_large")
            with path.open("rb") as source:
                raw = source.read(MAX_SOURCE_BYTES + 1)
            if len(raw) > MAX_SOURCE_BYTES:
                raise LegacyRecordIndexError("source_too_large")
            data = json.loads(raw.decode("utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise LegacyRecordIndexError("source_json_invalid") from exc
        summary = parse_record(data)
        if summary.record_type != "sleep" or "hbr_rr" not in summary.recognized_payloads:
            raise LegacyRecordIndexError("sleep_rr_contract_mismatch")
        updates = {
            "record_contract_version": CONTRACT_VERSION,
            "record_type": summary.record_type,
            "t0": summary.t0,
            "duration": summary.duration,
            "rows": summary.rows,
            "valid_rr_intervals": summary.valid_rr_intervals,
            "recognized_payloads": list(summary.recognized_payloads),
            "content_hash": hashlib.sha256(canonical_json(data)).hexdigest(),
            "accepted_at_utc": _formatted(created_at),
            PROVENANCE_FIELD: legacy_record_consent_marker(created_at),
        }
        if summary.captured_at_utc is not None:
            updates["captured_at_utc"] = summary.captured_at_utc
        if isinstance(data.get("metadata"), dict):
            updates["metadata"] = data["metadata"]
        return updates

    def run(self, apply=False):
        stats = Counter()
        users = {}
        indexed_users = {}
        for document in self._documents():
            stats["sleep_documents"] += 1
            owner = document.get("created_by")
            if not isinstance(owner, str) or not owner:
                stats["invalid_owner"] += 1
                continue
            user = self._user(owner, users)
            if not isinstance(user, dict):
                stats["missing_user"] += 1
                continue
            user_id = user.get("_id")
            if not isinstance(user_id, str) or not user_id:
                stats["invalid_user"] += 1
                continue
            if user.get("is_access_blocked") is True or (
                user.get("usage_flag") == UsageFlag.REJECTED.name
                or user.get("guidelines_acceptance_flag")
                == GuidelinesAcceptanceFlag.REJECTED.name
            ):
                stats["withdrawn_or_blocked"] += 1
                continue
            try:
                updates = self._updates(document)
            except (LegacyRecordIndexError, RecordExportError, RecordValidationError) as exc:
                stats["excluded:" + getattr(exc, "code", str(exc))] += 1
                continue
            stats["indexable_records"] += 1
            indexed_users[owner] = user_id
            if all(document.get(key) == value for key, value in updates.items()):
                stats["already_indexed_records"] += 1
                continue
            if apply:
                expected = {
                    key: document.get(key)
                    for key in (
                        "_id",
                        "created_by",
                        "created_at",
                        "file_path",
                        "file_type",
                        "source",
                    )
                }

                def mutate(current):
                    if any(current.get(key) != value for key, value in expected.items()):
                        raise LegacyRecordIndexError("record_changed")
                    return {**current, **updates}

                self.metadata_dao.mutate_doc(document["_id"], mutate)
                stats["updated_records"] += 1
            else:
                stats["would_update_records"] += 1

        stats["indexable_participants"] = len(indexed_users)
        for owner, user_id in indexed_users.items():
            user = users[owner]
            if user.get(PROVENANCE_FIELD) == legacy_consent_marker():
                stats["already_marked_participants"] += 1
                continue
            if apply:
                self.users_dao.mutate_doc(
                    user_id,
                    lambda current: {
                        **current,
                        PROVENANCE_FIELD: legacy_consent_marker(),
                    },
                )
                stats["marked_participants"] += 1
            else:
                stats["would_mark_participants"] += 1
        return dict(sorted(stats.items()))


def main():
    from config import config
    from dao.metadata_dao import image_metadata_dao
    from dao.users_dao import user_dao

    parser = argparse.ArgumentParser(
        description="Index retained Brainstem sleep records; dry-run by default."
    )
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm", default="")
    args = parser.parse_args()
    if args.apply and args.confirm != STUDY_ID:
        parser.error("--apply requires --confirm " + STUDY_ID)
    upload_root = Path(config["application"].get("upload_folder", "data"))
    if not upload_root.is_absolute():
        upload_root = Path.cwd() / upload_root
    result = LegacySleepRecordIndexer(
        image_metadata_dao, user_dao, upload_root
    ).run(apply=args.apply)
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
