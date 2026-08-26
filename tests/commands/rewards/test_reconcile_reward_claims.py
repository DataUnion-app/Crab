from web3.exceptions import TransactionNotFound

from commands.rewards.reconcile_reward_claims import reconcile_reward_claims
from dao.rewards_dao import RewardsDao


class Eth:
    def __init__(self, receipts):
        self.receipts = receipts

    def get_transaction_receipt(self, transaction_hash):
        if transaction_hash not in self.receipts:
            raise TransactionNotFound
        return {"status": self.receipts[transaction_hash]}


class Dao:
    def __init__(self, claims):
        self.claims = claims
        self.applied = []

    def iter_query(self, _query):
        yield from self.claims

    def reconcile_claim_receipt(self, claim_id, transaction_hash, succeeded):
        self.applied.append((claim_id, transaction_hash, succeeded))


def test_reconciliation_applies_only_confirmed_receipts():
    claims = [
        {"_id": "success", "status": "failed", "transaction_hash": "0x1"},
        {"_id": "revert", "status": "failed", "transaction_hash": "0x2"},
        {"_id": "unknown", "status": "failed", "transaction_hash": "0x3"},
        {"_id": "no-hash", "status": "transferring"},
    ]
    dao = Dao(claims)
    result = reconcile_reward_claims(
        dao, type("Web3", (), {"eth": Eth({"0x1": 1, "0x2": 0})})(), apply=True
    )
    assert result["confirmedSuccessful"] == 1
    assert result["confirmedReverted"] == 1
    assert result["unresolved"] == 1
    assert result["withoutTransactionIdentity"] == 1
    assert result["ok"] is False
    assert dao.applied == [
        ("success", "0x1", True),
        ("revert", "0x2", False),
    ]


def test_confirmed_revert_retains_audit_hash_but_becomes_retryable():
    document = {"status": "failed", "transaction_hash": "0xreverted"}
    dao = object.__new__(RewardsDao)
    dao.db_name = "rewards"
    dao.mutate_doc = lambda _claim_id, mutator: mutator(document)
    dao.reconcile_claim_receipt("claim", "0xreverted", False)
    assert document["status"] == "failed"
    assert "transaction_hash" not in document
    assert document["reverted_transaction_hash"] == "0xreverted"
    assert document["reason"] == "confirmed_chain_revert"
