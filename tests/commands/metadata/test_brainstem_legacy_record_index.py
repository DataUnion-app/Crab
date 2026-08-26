from copy import deepcopy
import json
from pathlib import Path

from commands.dataunions.brainstem.legacy_record_index import (
    LegacySleepRecordIndexer,
    PROVENANCE_FIELD,
    has_retrospective_research_consent,
    record_has_legacy_consent,
)


OWNER = "0x" + "a" * 40


class MetadataDao:
    def __init__(self, document):
        self.documents = {document["_id"]: deepcopy(document)}

    def iter_query(self, _query, batch_size):
        assert batch_size == 200
        yield from deepcopy(list(self.documents.values()))

    def mutate_doc(self, doc_id, mutator):
        self.documents[doc_id] = mutator(deepcopy(self.documents[doc_id]))


class UsersDao:
    def __init__(self):
        self.users = {
            "user-a": {
                "_id": "user-a",
                "public_address": OWNER,
                "usage_flag": "UNKNOWN",
                "guidelines_acceptance_flag": "UNKNOWN",
            }
        }

    def get_by_public_address(self, owner):
        return {
            "result": [
                deepcopy(user)
                for user in self.users.values()
                if user["public_address"] == owner
            ]
        }

    def mutate_doc(self, doc_id, mutator):
        self.users[doc_id] = mutator(deepcopy(self.users[doc_id]))


def record():
    return {
        "schemaVersion": "1.0.0",
        "type": "sleep",
        "timestamp": "2026-08-01_220000",
        "metadata": {"gender": "x", "year": 1980, "region": "EU"},
        "datasource": {
            "sensor": {
                "name": "generated",
                "id": "generated",
                "payloads": {
                    "hbr_rr": {
                        "dataType": "hbr_rr",
                        "format": "csv",
                        "data": "0,60,1000;1,60,1000",
                    }
                },
            }
        },
    }


def setup(tmp_path: Path):
    owner_dir = tmp_path / OWNER
    owner_dir.mkdir()
    source = owner_dir / "record.json"
    source.write_text(json.dumps(record()))
    document = {
        "_id": "record-a",
        "created_by": OWNER,
        "created_at": "2026-08-02T00:00:00.123456",
        "file_path": str(source),
        "file_type": "record",
        "source": "brainstem",
        "record_type": "sleep",
    }
    return MetadataDao(document), UsersDao()


def test_dry_run_is_read_only_and_apply_is_idempotent(tmp_path):
    metadata, users = setup(tmp_path)
    indexer = LegacySleepRecordIndexer(metadata, users, tmp_path)

    preview = indexer.run()
    assert preview["would_update_records"] == 1
    assert preview["would_mark_participants"] == 1
    assert PROVENANCE_FIELD not in metadata.documents["record-a"]
    assert not has_retrospective_research_consent(users.users["user-a"])

    applied = indexer.run(apply=True)
    assert applied["updated_records"] == 1
    assert applied["marked_participants"] == 1
    assert metadata.documents["record-a"]["record_contract_version"] == "brainstem-record-v1"
    assert record_has_legacy_consent(metadata.documents["record-a"])
    assert has_retrospective_research_consent(users.users["user-a"])

    repeated = indexer.run(apply=True)
    assert repeated["already_indexed_records"] == 1
    assert repeated["already_marked_participants"] == 1


def test_explicit_rejection_overrides_legacy_provenance(tmp_path):
    metadata, users = setup(tmp_path)
    LegacySleepRecordIndexer(metadata, users, tmp_path).run(apply=True)
    users.users["user-a"]["usage_flag"] = "REJECTED"
    assert not has_retrospective_research_consent(users.users["user-a"])


def test_pre_gate_record_is_not_indexed(tmp_path):
    metadata, users = setup(tmp_path)
    metadata.documents["record-a"]["created_at"] = "2024-10-01T00:00:00Z"
    result = LegacySleepRecordIndexer(metadata, users, tmp_path).run(apply=True)
    assert result["excluded:record_before_app_gate"] == 1
    assert PROVENANCE_FIELD not in metadata.documents["record-a"]
