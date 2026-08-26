import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from commands.dataunions.brainstem import c2d_export
from commands.dataunions.brainstem.c2d_export import (
    APNEA_RETROSPECTIVE_POLICY,
    BrainstemC2DExporter,
    C2DExportError,
    FULL_NIGHT_COMPATIBILITY_POLICY,
    METHODS_COHORT_POLICY,
    POLICY,
    SAMPLE_ENTROPY_COHORT_POLICY,
    SCHEMA,
    cohort_insight_policy,
)
from commands.dataunions.brainstem.legacy_record_index import (
    PROVENANCE_FIELD,
    legacy_consent_marker,
    legacy_record_consent_marker,
)


JOB_A = "a" * 64
JOB_B = "b" * 64
RELEASE_ID = "c" * 64
CONSENT_VERSION = "brainstem-tos-2026-07"
SECRET = "pseudonym-secret-that-is-long-enough-for-tests"
KEY_ID = "generated-v1"


def generated_record(device_canary, wallet_canary, interval=800):
    rows = ";".join(
        f"{second},60,{interval},{interval + 5}" for second in range(300)
    )
    return {
        "schemaVersion": "1.0",
        "type": "rest",
        "timestamp": "2026-07-21_120000",
        "metadata": {
            "gender": "generated",
            "year": 1990,
            "region": wallet_canary,
        },
        "datasource": {
            "sensor": {
                "name": "generated-sensor",
                "id": device_canary,
                "payloads": {
                    "hbr_rr": {
                        "dataType": "hbr_rr",
                        "format": "csv",
                        "data": rows,
                    }
                },
            }
        },
        "walletCanary": wallet_canary,
    }


class FakeMetadataDao:
    def __init__(self, documents):
        self.documents = documents
        self.saved = []

    def iter_query(self, _query, batch_size):
        assert batch_size == 500
        yield from self.documents

    def save(self, doc_id, document):
        self.saved = [
            (saved_id, saved_document)
            for saved_id, saved_document in self.saved
            if saved_id != doc_id
        ]
        self.saved.append((doc_id, document))

    def get_if_exists(self, doc_id):
        for saved_id, document in self.saved:
            if saved_id == doc_id:
                return True, document
        for document in self.documents:
            if document.get("_id") == doc_id:
                return True, document
        return False, None

    def mutate_doc(self, doc_id, mutator):
        exists, document = self.get_if_exists(doc_id)
        assert exists
        updated = mutator(dict(document))
        if updated is None:
            return document
        self.save(doc_id, updated)
        return updated


class FakeUsersDao:
    def __init__(self, users):
        self.users = users

    def get_by_public_address(self, address):
        user = self.users.get(address)
        return {"result": [user] if user else []}

    def get_doc_by_id(self, doc_id):
        for address, user in self.users.items():
            if user["_id"] == doc_id:
                return {**user, "public_address": address}
        raise KeyError(doc_id)


class FakeReleaseDao:
    def __init__(self, member_ids):
        self.document = {
            "document_type": "brainstem_c2d_cohort_release",
            "release_id": RELEASE_ID,
            "data_union": "brainstem",
            "purpose": POLICY,
            "consent_version": CONSENT_VERSION,
            "status": "active",
            "roster_user_ids": sorted(member_ids),
            "created_at": "2026-07-22T00:00:00Z",
            "activated_at": "2026-07-22T00:01:00Z",
            "expires_at": "2099-07-22T00:00:00Z",
        }

    def get_doc_by_id(self, doc_id):
        assert doc_id == f"brainstem-c2d-release:{RELEASE_ID}"
        return self.document


def make_full_night(record, index):
    record["type"] = "sleep"
    record["timestamp"] = f"2026-07-21_{index:02d}0000"
    record["datasource"]["sensor"]["payloads"]["hbr_rr"]["data"] = ";".join(
        f"{minute * 60},60," + ",".join([str(980 + index % 7)] * 60)
        for minute in range(301)
    )
    return record


def prepare_apnea_export(exporter, metadata):
    exporter.policy = APNEA_RETROSPECTIVE_POLICY
    exporter.release_dao.document["purpose"] = (
        APNEA_RETROSPECTIVE_POLICY.dataset_policy
    )
    for index, document in enumerate(metadata.documents):
        path = Path(document["file_path"])
        record = make_full_night(
            json.loads(path.read_text(encoding="utf-8")), index
        )
        path.write_text(json.dumps(record), encoding="utf-8")
        document["content_hash"] = hashlib.sha256(
            json.dumps(record, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()


def prepare_signal_compatibility_export(exporter, metadata):
    prepare_apnea_export(exporter, metadata)
    exporter.policy = FULL_NIGHT_COMPATIBILITY_POLICY
    exporter.release_dao.document["purpose"] = (
        FULL_NIGHT_COMPATIBILITY_POLICY.dataset_policy
    )


def fixture(tmp_path: Path, count=20):
    upload_root = tmp_path / "data"
    documents = []
    users = {}
    canaries = []
    for index in range(count):
        wallet = f"0xWALLET-CANARY-{index:04d}"
        device = f"DEVICE-CANARY-{index:04d}"
        filename = f"FILE-CANARY-{index:04d}.json"
        record = generated_record(device, wallet, 780 + index)
        address = f"wallet-{index}"
        path = upload_root / address / filename
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps(record), encoding="utf-8")
        canonical = json.dumps(
            record, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        documents.append({
            "_id": f"RECORD-CANARY-{index:04d}",
            "created_by": address,
            "file_path": str(path),
            "content_hash": hashlib.sha256(canonical).hexdigest(),
        })
        users[address] = {
            "_id": f"USER-CANARY-{index:04d}",
            "public_address": wallet,
            "usage_flag": "ACCEPTED",
            "guidelines_acceptance_flag": "ACCEPTED",
        }
        canaries.extend([wallet, device, filename, documents[-1]["_id"], users[address]["_id"]])
    metadata = FakeMetadataDao(documents)
    release_dao = FakeReleaseDao(user["_id"] for user in users.values())
    exporter = BrainstemC2DExporter(
        metadata_dao=metadata,
        users_dao=FakeUsersDao(users),
        audit_dao=metadata,
        release_dao=release_dao,
        upload_root=upload_root,
        pseudonym_secret=SECRET,
        pseudonym_key_id=KEY_ID,
        consent_version=CONSENT_VERSION,
    )
    return exporter, metadata, users, canaries


def test_generated_cohort_is_canonical_identifier_free_and_audited(tmp_path):
    exporter, metadata, _users, canaries = fixture(tmp_path)

    artifact = exporter.execute(JOB_A, RELEASE_ID)

    jsonschema = pytest.importorskip("jsonschema")
    schema_path = Path(__file__).parents[3] / "contracts" / (
        "brainstem.private-rr-cohort.v1.schema.json"
    )
    jsonschema.Draft202012Validator(
        json.loads(schema_path.read_text(encoding="utf-8"))
    ).validate(artifact.dataset)

    assert artifact.dataset["schema"] == SCHEMA
    assert artifact.dataset["policy"] == POLICY
    assert len(artifact.dataset["participants"]) == 20
    assert artifact.body == json.dumps(
        artifact.dataset, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    assert hashlib.sha256(artifact.body).hexdigest() == artifact.checksum
    assert all(
        set(participant) == {"subjectId", "recordings"}
        for participant in artifact.dataset["participants"]
    )
    text = artifact.body.decode("utf-8")
    assert JOB_A not in text
    assert RELEASE_ID not in text
    for canary in canaries:
        assert canary not in text

    audit = next(
        document
        for _doc_id, document in metadata.saved
        if document.get("outcome") == "released"
    )
    assert audit["outcome"] == "released"
    assert audit["pseudonym_key_id"] == KEY_ID
    assert artifact.pseudonym_key_id == KEY_ID
    assert audit["participant_count"] == 20
    assert audit["recording_count"] == 20
    audit_text = json.dumps(audit)
    assert JOB_A not in audit_text
    assert RELEASE_ID not in audit_text
    for canary in canaries:
        assert canary not in audit_text


def test_reviewed_methods_export_has_its_exact_identifier_free_shape(tmp_path):
    exporter, metadata, _users, canaries = fixture(tmp_path)
    exporter.policy = METHODS_COHORT_POLICY
    for index, document in enumerate(metadata.documents):
        path = Path(document["file_path"])
        record = json.loads(path.read_text(encoding="utf-8"))
        record["datasource"]["sensor"]["payloads"]["hbr_rr"]["data"] = ";".join(
            f"{second},60,{900 + (second + index) % 7}" for second in range(330)
        )
        path.write_text(json.dumps(record), encoding="utf-8")
        document["content_hash"] = hashlib.sha256(
            json.dumps(record, sort_keys=True, separators=(",", ":")).encode(
                "utf-8"
            )
        ).hexdigest()

    artifact = exporter.execute(JOB_A, RELEASE_ID)

    assert set(artifact.dataset) == {"schema", "participants"}
    assert artifact.dataset["schema"] == (
        "brainstem.resting-hrv-methods-cohort/v1"
    )
    assert len(artifact.dataset["participants"]) == 20
    assert all(
        len(participant["recordings"][0]["rrIntervalsMs"]) == 330
        for participant in artifact.dataset["participants"]
    )
    assert all(canary not in artifact.body.decode("utf-8") for canary in canaries)
    audit = next(
        document
        for _doc_id, document in metadata.saved
        if document.get("outcome") == "released"
    )
    assert audit["analysis_id"] == "brainstem.resting-hrv-methods/v1"
    assert audit["schema"] == "brainstem.resting-hrv-methods-cohort/v1"


def test_sample_entropy_export_has_one_compatible_recording_per_subject(tmp_path):
    exporter, metadata, _users, canaries = fixture(tmp_path)
    exporter.policy = SAMPLE_ENTROPY_COHORT_POLICY
    for index, document in enumerate(metadata.documents):
        path = Path(document["file_path"])
        record = json.loads(path.read_text(encoding="utf-8"))
        record["datasource"]["sensor"]["payloads"]["hbr_rr"]["data"] = ";".join(
            f"{second},60,{980 + (second + index) % 11}" for second in range(300)
        )
        path.write_text(json.dumps(record), encoding="utf-8")
        document["content_hash"] = hashlib.sha256(
            json.dumps(record, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()

    artifact = exporter.execute(JOB_A, RELEASE_ID)

    assert set(artifact.dataset) == {"schema", "participants"}
    assert artifact.dataset["schema"] == (
        "brainstem.resting-sample-entropy-cohort/v1"
    )
    assert len(artifact.dataset["participants"]) == 20
    assert all(
        len(participant["recordings"]) == 1
        and len(participant["recordings"][0]["rrIntervalsMs"]) == 300
        for participant in artifact.dataset["participants"]
    )
    assert all(canary not in artifact.body.decode() for canary in canaries)
    other_job = exporter.build(JOB_B, RELEASE_ID)[0]
    assert [item["subjectId"] for item in artifact.dataset["participants"]] != [
        item["subjectId"] for item in other_job.dataset["participants"]
    ]
    audit = next(
        document
        for _doc_id, document in metadata.saved
        if document.get("outcome") == "released"
    )
    assert audit["analysis_id"] == "brainstem.resting-rr-sample-entropy/v1"


def test_apnea_study_export_is_bounded_purpose_bound_and_identifier_free(tmp_path):
    exporter, metadata, _users, canaries = fixture(tmp_path, count=22)
    prepare_apnea_export(exporter, metadata)

    artifact = exporter.execute(JOB_A, RELEASE_ID)

    schema_path = Path(__file__).parents[3] / "contracts" / (
        "brainstem.full-night-rr-cohort.v1.schema.json"
    )
    pytest.importorskip("jsonschema").Draft202012Validator(
        json.loads(schema_path.read_text(encoding="utf-8"))
    ).validate(artifact.dataset)
    assert artifact.dataset["schema"] == APNEA_RETROSPECTIVE_POLICY.schema
    assert artifact.dataset["policy"] == APNEA_RETROSPECTIVE_POLICY.dataset_policy
    assert len(artifact.dataset["participants"]) == 22
    assert all(
        participant["recordings"][0]["intervalSemantics"]
        == "detector_rr_unclassified"
        and participant["recordings"][0]["allowedUse"]
        == "aggregate_method_compatibility_only"
        for participant in artifact.dataset["participants"]
    )
    assert all(canary not in artifact.body.decode() for canary in canaries)


def test_apnea_study_export_rejects_nineteen_participants(tmp_path):
    exporter, metadata, _users, _canaries = fixture(tmp_path, count=19)
    prepare_apnea_export(exporter, metadata)
    with pytest.raises(C2DExportError, match="participant_privacy_floor"):
        exporter.execute(JOB_A, RELEASE_ID)


def test_apnea_api_policy_is_default_off(monkeypatch):
    monkeypatch.delenv("BRAINSTEM_APNEA_REAL_DATA_ENABLED", raising=False)
    with pytest.raises(C2DExportError, match="analysis_disabled"):
        cohort_insight_policy(APNEA_RETROSPECTIVE_POLICY.analysis_id)
    monkeypatch.setenv("BRAINSTEM_APNEA_REAL_DATA_ENABLED", "true")
    assert (
        cohort_insight_policy(APNEA_RETROSPECTIVE_POLICY.analysis_id)
        is APNEA_RETROSPECTIVE_POLICY
    )


def test_signal_compatibility_policy_has_its_own_default_off_gate(monkeypatch):
    monkeypatch.delenv(
        "BRAINSTEM_FULL_NIGHT_COMPATIBILITY_REAL_DATA_ENABLED", raising=False
    )
    monkeypatch.setenv("BRAINSTEM_APNEA_REAL_DATA_ENABLED", "true")
    with pytest.raises(C2DExportError, match="analysis_disabled"):
        cohort_insight_policy(FULL_NIGHT_COMPATIBILITY_POLICY.analysis_id)
    monkeypatch.setenv(
        "BRAINSTEM_FULL_NIGHT_COMPATIBILITY_REAL_DATA_ENABLED", "true"
    )
    assert (
        cohort_insight_policy(FULL_NIGHT_COMPATIBILITY_POLICY.analysis_id)
        is FULL_NIGHT_COMPATIBILITY_POLICY
    )


def test_signal_compatibility_export_requires_four_review_commitments(tmp_path):
    exporter, metadata, _users, _canaries = fixture(tmp_path, count=22)
    prepare_signal_compatibility_export(exporter, metadata)
    with pytest.raises(C2DExportError, match="study_binding_required"):
        exporter.execute(JOB_A, RELEASE_ID)
    binding = {
        "proposalId": "study_a",
        "revisionId": "revision_b",
        "revisionSha256": "c" * 64,
        "releaseVersion": "1.0.0",
        "releaseSha256": "d" * 64,
        "reviewDecisions": [
            {"domain": domain, "decisionSha256": format(index, "x") * 64}
            for index, domain in enumerate(
                ("scientific", "privacy", "security", "ethics"), 1
            )
        ],
    }
    artifact = exporter.execute(JOB_A, RELEASE_ID, binding)
    schema_path = Path(__file__).parents[3] / "contracts" / (
        "brainstem.full-night-rr-cohort.v1.schema.json"
    )
    pytest.importorskip("jsonschema").Draft202012Validator(
        json.loads(schema_path.read_text(encoding="utf-8"))
    ).validate(artifact.dataset)
    assert artifact.dataset["policy"] == FULL_NIGHT_COMPATIBILITY_POLICY.dataset_policy
    audit = next(
        item
        for _doc_id, item in metadata.saved
        if item.get("outcome") == "released"
    )
    assert audit["study_proposal_id"] == "study_a"
    assert audit["study_revision_sha256"] == "c" * 64
    assert audit["study_release_sha256"] == "d" * 64
    assert audit["selector_version"] == "brainstem.full-night-rr-selector/v1"


def test_full_night_selector_counts_a_release_member_without_sleep_records(tmp_path):
    exporter, metadata, users, _canaries = fixture(tmp_path, count=22)
    prepare_signal_compatibility_export(exporter, metadata)
    users["wallet-missing"] = {
        "_id": "USER-CANARY-MISSING",
        "public_address": "not-used-by-the-fake",
        "usage_flag": "ACCEPTED",
        "guidelines_acceptance_flag": "ACCEPTED",
    }
    exporter.release_dao.document["roster_user_ids"].append("USER-CANARY-MISSING")

    selection = exporter.select_full_night(RELEASE_ID)

    assert selection.stats["participant_count"] == 22
    assert selection.stats["no_qualifying_full_night_participant_count"] == 1


def test_full_night_selector_accepts_only_provenanced_legacy_records(tmp_path):
    exporter, metadata, users, _canaries = fixture(tmp_path, count=22)
    prepare_signal_compatibility_export(exporter, metadata)
    for user in users.values():
        user["usage_flag"] = "UNKNOWN"
        user["guidelines_acceptance_flag"] = "UNKNOWN"
        user[PROVENANCE_FIELD] = legacy_consent_marker()
    for document in metadata.documents:
        document[PROVENANCE_FIELD] = legacy_record_consent_marker(
            datetime(2026, 7, 22, tzinfo=timezone.utc)
        )
    metadata.documents[0].pop(PROVENANCE_FIELD)

    selection = exporter.select_full_night(RELEASE_ID)

    assert selection.stats["participant_count"] == 21
    assert selection.stats["no_qualifying_full_night_participant_count"] == 1


def test_full_night_selector_fails_closed_when_a_release_member_cannot_be_loaded(
    tmp_path,
):
    exporter, metadata, users, _canaries = fixture(tmp_path, count=22)
    prepare_signal_compatibility_export(exporter, metadata)
    missing_id = next(iter(users.values()))["_id"]
    original_get = exporter.users_dao.get_doc_by_id

    def unavailable(doc_id):
        if doc_id == missing_id:
            raise RuntimeError("generated lookup failure")
        return original_get(doc_id)

    exporter.users_dao.get_doc_by_id = unavailable
    with pytest.raises(C2DExportError, match="participant_lookup_unavailable"):
        exporter.select_full_night(RELEASE_ID)


def test_full_night_selector_rejects_more_than_the_bounded_cohort(
    tmp_path, monkeypatch
):
    exporter, metadata, _users, _canaries = fixture(tmp_path, count=22)
    prepare_signal_compatibility_export(exporter, metadata)
    monkeypatch.setattr(c2d_export, "MAX_FULL_NIGHT_PARTICIPANTS", 21)

    with pytest.raises(C2DExportError, match="participant_limit_exceeded"):
        exporter.select_full_night(RELEASE_ID)


def test_export_fails_if_a_selected_source_is_deleted_before_release(tmp_path):
    exporter, metadata, _users, _canaries = fixture(tmp_path)
    deleted_id = metadata.documents[0]["_id"]
    original_get = metadata.get_if_exists

    def deleted_source(doc_id):
        if doc_id == deleted_id:
            return False, None
        return original_get(doc_id)

    metadata.get_if_exists = deleted_source
    with pytest.raises(C2DExportError, match="materialization_source_stale"):
        exporter.execute(JOB_A, RELEASE_ID)


def test_consent_is_rechecked_and_subject_ids_rotate_by_job(tmp_path):
    exporter, _metadata, users, _canaries = fixture(tmp_path)
    first = exporter.execute(JOB_A, RELEASE_ID)
    other_job = exporter.execute(JOB_B, RELEASE_ID)

    first_ids = [item["subjectId"] for item in first.dataset["participants"]]
    assert first_ids != [item["subjectId"] for item in other_job.dataset["participants"]]
    with pytest.raises(C2DExportError, match="job_id_completed"):
        exporter.execute(JOB_A, RELEASE_ID)
    with pytest.raises(C2DExportError, match="job_id_reused"):
        exporter.execute(JOB_A, "d" * 64)

    users["wallet-0"]["guidelines_acceptance_flag"] = "REJECTED"
    with pytest.raises(C2DExportError, match="participant_privacy_floor"):
        exporter.execute("d" * 64, RELEASE_ID)


def test_transient_export_failure_can_retry_the_same_job(tmp_path):
    exporter, _metadata, _users, _canaries = fixture(tmp_path)
    build = exporter.build
    attempts = [0]

    def flaky(job_id, release_id):
        attempts[0] += 1
        if attempts[0] == 1:
            raise C2DExportError("temporary_failure", 503)
        return build(job_id, release_id)

    exporter.build = flaky
    with pytest.raises(C2DExportError, match="temporary_failure"):
        exporter.execute(JOB_A, RELEASE_ID)

    assert exporter.execute(JOB_A, RELEASE_ID).dataset["schema"] == SCHEMA


def test_subject_ids_rotate_with_pseudonym_key_version(tmp_path):
    exporter, _metadata, _users, _canaries = fixture(tmp_path)
    first = exporter.build(JOB_A, RELEASE_ID)[0]
    exporter.pseudonym_key_id = "generated-v2"
    rotated = exporter.build(JOB_A, RELEASE_ID)[0]

    assert first.pseudonym_key_id == KEY_ID
    assert rotated.pseudonym_key_id == "generated-v2"
    assert [item["subjectId"] for item in first.dataset["participants"]] != [
        item["subjectId"] for item in rotated.dataset["participants"]
    ]


def test_invalid_rr_record_is_excluded_without_leaking_its_owner(tmp_path):
    exporter, _metadata, _users, canaries = fixture(tmp_path, count=1)
    path = Path(exporter.metadata_dao.documents[0]["file_path"])
    record = json.loads(path.read_text(encoding="utf-8"))
    record["datasource"]["sensor"]["payloads"]["hbr_rr"]["data"] = (
        "0,60,not-a-number;299,60,800"
    )
    path.write_text(json.dumps(record), encoding="utf-8")
    exporter.metadata_dao.documents[0]["content_hash"] = hashlib.sha256(
        json.dumps(record, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()

    with pytest.raises(C2DExportError, match="participant_privacy_floor"):
        exporter.execute(JOB_A, RELEASE_ID)


def test_hash_mismatch_fails_closed_and_records_redacted_reason(tmp_path):
    exporter, metadata, _users, canaries = fixture(tmp_path, count=1)
    exporter.metadata_dao.documents[0]["content_hash"] = "0" * 64

    with pytest.raises(C2DExportError, match="source_hash_mismatch"):
        exporter.execute(JOB_A, RELEASE_ID)

    audit = next(
        document
        for _doc_id, document in reversed(metadata.saved)
        if document.get("outcome") == "rejected"
    )
    assert audit["outcome"] == "rejected"
    assert audit["reason"] == "source_hash_mismatch"
    assert all(canary not in json.dumps(audit) for canary in canaries)


def test_source_path_cannot_cross_into_another_participant_directory(tmp_path):
    exporter, _metadata, _users, _canaries = fixture(tmp_path, count=2)
    first, second = exporter.metadata_dao.documents
    first["file_path"] = second["file_path"]
    first["content_hash"] = second["content_hash"]

    with pytest.raises(C2DExportError, match="source_path_outside_upload_root"):
        exporter.execute(JOB_A, RELEASE_ID)


def test_participant_limit_rejects_instead_of_truncating(tmp_path, monkeypatch):
    exporter, _metadata, _users, _canaries = fixture(tmp_path, count=2)
    monkeypatch.setattr(c2d_export, "MAX_PARTICIPANTS", 1)

    with pytest.raises(C2DExportError, match="participant_limit_exceeded"):
        exporter.execute(JOB_A, RELEASE_ID)


@pytest.mark.parametrize("job_id", ["", "A" * 64, "a" * 63, "not-a-job"])
def test_job_id_must_be_internal_opaque_hex(tmp_path, job_id):
    exporter, _metadata, _users, _canaries = fixture(tmp_path, count=1)
    with pytest.raises(C2DExportError, match="invalid_job_id"):
        exporter.execute(job_id, RELEASE_ID)


def test_release_roster_and_deletion_are_rechecked_at_export(tmp_path):
    exporter, _metadata, users, canaries = fixture(tmp_path, count=3)
    exporter.release_dao.document["roster_user_ids"] = [users["wallet-0"]["_id"]]

    with pytest.raises(C2DExportError, match="participant_privacy_floor"):
        exporter.execute(JOB_A, RELEASE_ID)

    exporter.metadata_dao.documents = [
        document
        for document in exporter.metadata_dao.documents
        if document["created_by"] != "wallet-0"
    ]
    with pytest.raises(C2DExportError, match="participant_privacy_floor"):
        exporter.execute(JOB_B, RELEASE_ID)


def test_value_manifest_receives_only_the_private_contribution_set(tmp_path):
    exporter, _metadata, _users, canaries = fixture(tmp_path)

    class FakeValueService:
        call = None

        def record_export(self, *args):
            self.call = args

    value_service = FakeValueService()
    exporter.value_service = value_service
    artifact = exporter.execute(JOB_A, RELEASE_ID)

    (
        job_id,
        release_id,
        input_sha256,
        schema,
        policy,
        contributors,
    ) = value_service.call
    assert (job_id, release_id, input_sha256, schema, policy) == (
        JOB_A,
        RELEASE_ID,
        artifact.checksum,
        SCHEMA,
        POLICY,
    )
    assert len(contributors) == 20
    assert all(
        set(contributor) == {
            "internal_user_id",
            "public_address",
            "record_owner",
            "records",
        }
        for contributor in contributors
    )
    assert all(canary not in artifact.body.decode("utf-8") for canary in canaries)


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        ({"status": "draft"}, "release_not_active"),
        ({"expires_at": "2020-01-01T00:00:00Z"}, "release_expired"),
        ({"purpose": "researcher-selected"}, "release_contract_mismatch"),
        ({"consent_version": "other-version"}, "release_contract_mismatch"),
        ({"data_union": "other"}, "release_contract_mismatch"),
    ],
)
def test_inactive_expired_or_mismatched_release_fails_closed(
    tmp_path, change, reason
):
    exporter, _metadata, _users, _canaries = fixture(tmp_path, count=1)
    exporter.release_dao.document.update(change)
    with pytest.raises(C2DExportError, match=reason):
        exporter.execute(JOB_A, RELEASE_ID)


@pytest.mark.parametrize("release_id", ["", "A" * 64, "c" * 63, "named-cohort"])
def test_release_id_must_be_opaque_hex(tmp_path, release_id):
    exporter, _metadata, _users, _canaries = fixture(tmp_path, count=1)
    with pytest.raises(C2DExportError, match="invalid_release_id"):
        exporter.execute(JOB_A, release_id)
