from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path

import pytest

from commands.dataunions.brainstem.c2d_export import C2DExportError
from commands.dataunions.brainstem.record_contract import parse_record
from commands.dataunions.brainstem.recording_feasibility_export import (
    BrainstemRecordingFeasibilityExporter,
)
from commands.dataunions.brainstem.recording_feasibility_study import (
    ASSIGNMENT_POLICY,
    CONSENT_CONTENT_SHA256,
    CONSENT_VERSION,
    PROTOCOL_VERSION,
    STUDY_ID,
    protocol_sha256,
)


JOB_A = "a" * 64
JOB_B = "b" * 64
SECRET = "generated-study-secret-" + "s" * 32
KEY_ID = "generated-v1"
ASSIGNMENT_START = datetime(2026, 8, 2, tzinfo=timezone.utc)


class FakeDao:
    def __init__(self, documents=()):
        self.documents = list(documents)
        self.saved = []

    def iter_query(self, _query, batch_size):
        assert batch_size == 500
        yield from deepcopy(self.documents)

    def save(self, doc_id, document):
        self.saved.append((doc_id, deepcopy(document)))


class FakeUsersDao:
    def __init__(self, users):
        self.users = users

    def get_doc_by_id(self, user_id):
        if user_id not in self.users:
            raise RuntimeError("not found")
        return deepcopy(self.users[user_id])


class FakeCaptureVerifier:
    def __init__(self, approved):
        self.approved = set(approved)

    def __call__(self, document):
        return document.get("_id") in self.approved


def enrollment(user_id, state="active"):
    return {
        "document_type": "brainstem_study_enrollment",
        "user_id": user_id,
        "study_id": STUDY_ID,
        "protocol_version": PROTOCOL_VERSION,
        "protocol_sha256": protocol_sha256(),
        "consent_version": CONSENT_VERSION,
        "consent_content_sha256": CONSENT_CONTENT_SHA256,
        "assignment_policy": ASSIGNMENT_POLICY,
        "state": state,
        "enrolled_at": int(
            (ASSIGNMENT_START - timedelta(hours=12)).timestamp()
        ),
        "assignment_starts_at": int(ASSIGNMENT_START.timestamp()),
        "assignment_ends_at": int(
            (ASSIGNMENT_START + timedelta(days=14)).timestamp()
        ),
        "withdrawn_at": (
            None
            if state == "active"
            else int((ASSIGNMENT_START + timedelta(days=1)).timestamp())
        ),
    }


def record_document(upload_root, owner, record_id, day):
    captured = ASSIGNMENT_START + timedelta(days=day, minutes=1)
    accepted = captured + timedelta(minutes=5)
    rows = ";".join(f"{second},60,800" for second in range(300))
    source = {
        "schemaVersion": "1.0",
        "type": "rest",
        "timestamp": captured.strftime("%Y-%m-%d_%H%M%S"),
        "captureTime": {
            "basis": "rfc3339-utc",
            "startedAt": captured.strftime("%Y-%m-%dT%H:%M:%SZ"),
        },
        "datasource": {
            "sensor": {
                "name": "GENERATED-SENSOR-CANARY",
                "id": "GENERATED-DEVICE-CANARY",
                "payloads": {
                    "hbr_rr": {
                        "dataType": "hbr_rr",
                        "format": "csv",
                        "data": rows,
                    }
                },
            }
        },
    }
    summary = parse_record(source)
    path = upload_root / owner / f"{record_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(source), encoding="utf-8")
    canonical = json.dumps(
        source, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return {
        "_id": record_id,
        "created_by": owner,
        "file_path": str(path),
        "content_hash": hashlib.sha256(canonical).hexdigest(),
        "file_type": "record",
        "record_contract_version": "brainstem-record-v1",
        "record_type": "rest",
        "recognized_payloads": ["hbr_rr"],
        "duration": summary.duration,
        "valid_rr_intervals": summary.valid_rr_intervals,
        "accepted_at_utc": accepted.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "captured_at_utc": captured.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def fixture(tmp_path, participants=3, recordings_per_participant=2):
    upload_root = tmp_path / "data"
    users = {}
    enrollments = []
    documents = []
    canaries = [
        "GENERATED-SENSOR-CANARY",
        "GENERATED-DEVICE-CANARY",
    ]
    for index in range(participants):
        user_id = f"GENERATED-USER-CANARY-{index}"
        owner = f"GENERATED-WALLET-CANARY-{index}"
        users[user_id] = {
            "_id": user_id,
            "public_address": owner,
            "usage_flag": "ACCEPTED",
            "guidelines_acceptance_flag": "ACCEPTED",
            "is_access_blocked": False,
        }
        enrollments.append(enrollment(user_id))
        canaries.extend([user_id, owner])
        if index == participants - 1:
            continue
        for day in range(recordings_per_participant):
            record_id = f"GENERATED-RECORD-CANARY-{index}-{day}"
            documents.append(
                record_document(upload_root, owner, record_id, day)
            )
            canaries.append(record_id)

    metadata = FakeDao(documents)
    enrollment_dao = FakeDao(enrollments)
    audit = FakeDao()
    verifier = FakeCaptureVerifier(
        document["_id"] for document in documents
    )
    exporter = BrainstemRecordingFeasibilityExporter(
        metadata_dao=metadata,
        users_dao=FakeUsersDao(users),
        enrollment_dao=enrollment_dao,
        audit_dao=audit,
        upload_root=upload_root,
        pseudonym_secret=SECRET,
        pseudonym_key_id=KEY_ID,
        capture_time_verifier=verifier,
    )
    return exporter, metadata, enrollment_dao, users, audit, verifier, canaries


def test_generated_materialization_is_canonical_private_and_job_scoped(tmp_path):
    exporter, _metadata, _enrollments, _users, audit, _verifier, canaries = (
        fixture(tmp_path)
    )

    first = exporter.execute(JOB_A)
    repeated = exporter.execute(JOB_A)
    other_job = exporter.execute(JOB_B)

    assert first.body == json.dumps(
        first.dataset, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    assert hashlib.sha256(first.body).hexdigest() == first.checksum
    assert first.pseudonym_key_id == KEY_ID
    assert first.dataset["schema"] == "brainstem.recording-feasibility-rr/v1"
    assert first.dataset["policy"] == "brainstem.recording-feasibility-rr/14d-v1"
    assert first.dataset["protocol"] == {
        "id": STUDY_ID,
        "version": PROTOCOL_VERSION,
        "protocolSha256": protocol_sha256(),
        "consentVersion": CONSENT_VERSION,
        "consentContentSha256": CONSENT_CONTENT_SHA256,
        "assignmentPolicy": ASSIGNMENT_POLICY,
        "collectionDays": 14,
    }
    assert sorted(
        len(item["recordings"]) for item in first.dataset["participants"]
    ) == [0, 2, 2]
    assert [
        item["subjectId"] for item in first.dataset["participants"]
    ] == [item["subjectId"] for item in repeated.dataset["participants"]]
    assert [
        item["subjectId"] for item in first.dataset["participants"]
    ] != [item["subjectId"] for item in other_job.dataset["participants"]]
    text = first.body.decode("utf-8") + json.dumps(audit.saved)
    assert JOB_A not in text
    assert JOB_B not in text
    assert all(canary not in text for canary in canaries)
    assert all(document[1]["pseudonym_key_id"] == KEY_ID for document in audit.saved)


def test_withdrawal_and_current_consent_exclude_participants(tmp_path):
    exporter, _metadata, enrollments, users, _audit, _verifier, _canaries = (
        fixture(tmp_path)
    )
    enrollments.documents[0] = enrollment(
        enrollments.documents[0]["user_id"], state="withdrawn"
    )
    users[enrollments.documents[1]["user_id"]]["usage_flag"] = "REJECTED"

    artifact = exporter.execute(JOB_A)

    assert len(artifact.dataset["participants"]) == 1
    assert artifact.dataset["participants"][0]["recordings"] == []


def test_deletion_and_unverified_time_remove_records_not_denominator(tmp_path):
    exporter, metadata, _enrollments, _users, _audit, verifier, _canaries = (
        fixture(tmp_path, participants=2, recordings_per_participant=2)
    )
    deleted = metadata.documents.pop(0)
    verifier.approved.remove(metadata.documents[0]["_id"])

    artifact = exporter.execute(JOB_A)

    assert len(artifact.dataset["participants"]) == 2
    assert sum(
        len(item["recordings"]) for item in artifact.dataset["participants"]
    ) == 0
    assert deleted["_id"] not in artifact.body.decode("utf-8")


def test_historical_capture_is_excluded_even_when_verifier_approves(tmp_path):
    exporter, metadata, _enrollments, _users, _audit, _verifier, _canaries = (
        fixture(tmp_path, participants=2, recordings_per_participant=1)
    )
    metadata.documents[0]["captured_at_utc"] = "2026-08-01T23:59:59Z"

    artifact = exporter.execute(JOB_A)

    assert all(
        item["recordings"] == [] for item in artifact.dataset["participants"]
    )


def test_source_hash_or_summary_drift_fails_closed(tmp_path):
    exporter, metadata, _enrollments, _users, audit, _verifier, _canaries = (
        fixture(tmp_path, participants=2, recordings_per_participant=1)
    )
    metadata.documents[0]["content_hash"] = "0" * 64

    with pytest.raises(C2DExportError, match="source_hash_mismatch"):
        exporter.execute(JOB_A)
    assert audit.saved[-1][1]["reason"] == "source_hash_mismatch"

    metadata.documents[0]["content_hash"] = hashlib.sha256(
        json.dumps(
            json.loads(
                Path(metadata.documents[0]["file_path"]).read_text(
                    encoding="utf-8"
                )
            ),
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    metadata.documents[0]["valid_rr_intervals"] += 1
    with pytest.raises(C2DExportError, match="source_summary_mismatch"):
        exporter.execute(JOB_A)


def test_duplicate_enrollment_and_missing_verifier_fail_closed(tmp_path):
    exporter, _metadata, enrollments, _users, _audit, _verifier, _canaries = (
        fixture(tmp_path, participants=2, recordings_per_participant=0)
    )
    enrollments.documents.append(deepcopy(enrollments.documents[0]))
    with pytest.raises(C2DExportError, match="enrollment_set_invalid"):
        exporter.execute(JOB_A)

    exporter.capture_time_verifier = None
    with pytest.raises(C2DExportError, match="export_configuration_invalid"):
        exporter.build(JOB_A)

    exporter.capture_time_verifier = lambda _document: True
    exporter.pseudonym_key_id = ""
    with pytest.raises(C2DExportError, match="export_configuration_invalid"):
        exporter.build(JOB_A)


def test_invalid_job_and_duplicate_wallet_fail_closed(tmp_path):
    exporter, _metadata, enrollments, users, audit, _verifier, _canaries = (
        fixture(tmp_path, participants=2, recordings_per_participant=0)
    )
    with pytest.raises(C2DExportError, match="invalid_job_id"):
        exporter.execute(None)
    assert audit.saved[-1][1]["reason"] == "invalid_job_id"

    users[enrollments.documents[1]["user_id"]]["public_address"] = users[
        enrollments.documents[0]["user_id"]
    ]["public_address"]
    with pytest.raises(C2DExportError, match="participant_wallet_invalid"):
        exporter.execute(JOB_A)
