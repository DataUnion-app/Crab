from copy import deepcopy
from pathlib import Path

from commands.metadata.delete_records_command import DeleteRecordsCommand
from dao.rewards_dao import RewardsDao


class FakeMetadataDao:
    def __init__(self, documents):
        self.documents = {item["_id"]: deepcopy(item) for item in documents}

    def query_all(self, query):
        owner = query["selector"]["created_by"]
        return [
            deepcopy(item)
            for item in self.documents.values()
            if item.get("created_by") == owner and item.get("file_type") == "record"
        ]

    def delete_doc(self, doc_id):
        del self.documents[doc_id]


class FakeUsersDao:
    def __init__(self, user):
        self.user = deepcopy(user)

    def get_by_public_address(self, address):
        return {"result": [deepcopy(self.user)] if self.user["public_address"] == address else []}

    def mutate_doc(self, doc_id, mutator):
        assert doc_id == self.user["_id"]
        self.user = mutator(deepcopy(self.user))


class FakeRewardsDao:
    def __init__(self, known_record_ids):
        self.voided = []
        self.known_record_ids = set(known_record_ids)

    def void_orphaned_brainstem_eligibilities(self, _address, surviving_record_ids):
        self.voided.extend(
            sorted(self.known_record_ids - set(surviving_record_ids))
        )
        return len(self.voided)


def record_document(doc_id, owner, path):
    return {
        "_id": doc_id,
        "created_by": owner,
        "file_type": "record",
        "file_path": str(path),
        "storage": "",
        "record_contract_version": "brainstem-record-v1",
        "recognized_payloads": ["hbr_rr"],
        "record_type": "rest",
        "rows": 300,
        "duration": 300,
    }


def test_deletion_repairs_projection_even_when_a_raw_file_is_missing(tmp_path):
    upload_root = tmp_path / "data"
    present = upload_root / "wallet" / "present.json"
    missing = upload_root / "wallet" / "missing.json"
    present.parent.mkdir(parents=True)
    present.write_text("{}", encoding="utf-8")
    metadata = FakeMetadataDao([
        record_document("record-1", "wallet", present),
        record_document("record-2", "wallet", missing),
    ])
    users = FakeUsersDao({
        "_id": "user-1",
        "public_address": "wallet",
        "usage_flag": "ACCEPTED",
        "guidelines_acceptance_flag": "ACCEPTED",
        "recording_data": {"total_amount": 2},
        "brainstem_record_ids": ["record-1", "record-2"],
    })
    rewards = FakeRewardsDao({"record-1", "record-2"})
    command = DeleteRecordsCommand(
        "wallet", metadata, users, rewards, upload_root=upload_root
    )

    command.execute()

    assert command.successful is True
    assert metadata.documents == {}
    assert not present.exists()
    assert "recording_data" not in users.user
    assert "brainstem_record_ids" not in users.user
    assert rewards.voided == ["record-1", "record-2"]


def test_path_escape_is_retained_and_projection_rebuilt_from_survivor(tmp_path):
    upload_root = tmp_path / "data"
    outside = tmp_path / "outside.json"
    outside.write_text("{}", encoding="utf-8")
    document = record_document("record-1", "wallet", outside)
    metadata = FakeMetadataDao([document])
    users = FakeUsersDao({"_id": "user-1", "public_address": "wallet"})
    rewards = FakeRewardsDao({"record-1"})
    command = DeleteRecordsCommand(
        "wallet", metadata, users, rewards, upload_root=upload_root
    )

    command.execute()

    assert command.successful is False
    assert outside.exists()
    assert set(metadata.documents) == {"record-1"}
    assert users.user["brainstem_record_ids"] == ["record-1"]
    assert users.user["recording_data"]["total_amount"] == 1
    assert rewards.voided == []


class RewardStore:
    def __init__(self):
        self.documents = {
            "created": {
                "_id": "created",
                "document_type": "brainstem_reward_eligibility",
                "record_id": "record-1",
                "status": "created",
            },
            "paid": {
                "_id": "paid",
                "document_type": "brainstem_reward_eligibility",
                "record_id": "record-1",
                "status": "paid",
            },
        }

    def query_all(self, query):
        selector = query["selector"]
        record_ids = selector.get("record_id", {}).get("$in")
        return [
            deepcopy(item)
            for item in self.documents.values()
            if (record_ids is None or item["record_id"] in record_ids)
            and item["status"] == "created"
            and (
                "public_address" not in selector
                or item.get("public_address") == selector["public_address"]
            )
        ]

    def mutate_doc(self, doc_id, mutator):
        updated = mutator(deepcopy(self.documents[doc_id]))
        if updated is not None:
            self.documents[doc_id] = updated

    def void_unclaimed_brainstem_eligibilities(self, record_ids):
        return RewardsDao.void_unclaimed_brainstem_eligibilities(
            self, record_ids
        )


def test_only_unclaimed_reward_eligibility_is_voided():
    store = RewardStore()

    count = RewardsDao.void_unclaimed_brainstem_eligibilities(
        store, ["record-1"]
    )

    assert count == 1
    assert store.documents["created"]["status"] == "voided"
    assert store.documents["created"]["void_reason"] == "source_record_deleted"
    assert store.documents["paid"]["status"] == "paid"


def test_retry_repair_finds_orphaned_unclaimed_eligibility():
    store = RewardStore()
    store.documents["created"]["public_address"] = "wallet"
    store.documents["paid"]["public_address"] = "wallet"

    count = RewardsDao.void_orphaned_brainstem_eligibilities(
        store, "wallet", []
    )

    assert count == 1
    assert store.documents["created"]["status"] == "voided"
    assert store.documents["paid"]["status"] == "paid"
