import sys
from types import ModuleType, SimpleNamespace

sys.modules.setdefault("pandas", ModuleType("pandas"))
from commands.metadata.create_new_entity import create_brainstem_entity as module
from models.metadata.metadata_models import EntitySubType


def test_deduplicated_record_is_upgraded_to_the_current_contract(monkeypatch):
    existing = {
        "_id": "record-1",
        "_rev": "1-a",
        "file_type": EntitySubType.record,
        "brainstem_record_ids": ["record-1"],
    }

    class Metadata:
        updated = None

        def get_if_exists(self, _doc_id):
            return True, dict(existing)

        def mutate_doc(self, _doc_id, mutate):
            self.updated = mutate(dict(existing))
            return self.updated

    metadata = Metadata()
    monkeypatch.setattr(module, "image_metadata_dao", metadata)
    monkeypatch.setattr(
        module.user_dao,
        "get_by_public_address",
        lambda _address: {
            "result": [{"_id": "user-1", "brainstem_record_ids": ["record-1"]}]
        },
    )

    summary = SimpleNamespace(
        record_type="rest",
        t0=1,
        duration=300,
        rows=300,
        valid_rr_intervals=299,
        recognized_payloads=("hbr_rr",),
        reward_eligible=False,
        reward_reason="not_eligible",
        captured_at_utc="2026-07-29T00:00:00Z",
    )
    command = module.CreateBrainStemEntityCommand(
        "0x" + "1" * 40,
        "/tmp/not-read.json",
        EntitySubType.record,
        "application/json",
        "record.json",
        document_id="record-1",
        record_data={"datasource": {"sensor": {"name": "Brainstem"}}},
        record_summary=summary,
        content_hash="a" * 64,
    )

    assert command.execute() == "record-1"
    assert metadata.updated["record_contract_version"] == "brainstem-record-v1"
    assert metadata.updated["valid_rr_intervals"] == 299
    assert metadata.updated["captured_at_utc"] == "2026-07-29T00:00:00Z"
    assert metadata.updated["accepted_at_utc"].endswith("Z")
