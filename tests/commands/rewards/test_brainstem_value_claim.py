from copy import deepcopy
from datetime import datetime

from commands.rewards import calculate_reward as calculate_module
from commands.rewards import claim_reward_command as claim_module
from commands.rewards.brainstem_claim_preview import preview_brainstem_claim
from commands.rewards.calculate_reward import brainstem_reward_commitment
from commands.rewards.claim_reward_command import ClaimRewardCommand
from models.metadata.metadata_models import Source
from models.rewards.rewards_model import ClaimRewardErrorMessages


WALLET = "0x" + "1" * 40
PRIVATE_KEY = "0x" + "44" * 32


class FakeUsers:
    def get_by_public_address(self, address):
        assert address == WALLET
        return {
            "result": [{
                "_id": "user",
                "public_address": WALLET,
                "usage_flag": "REJECTED",
                "guidelines_acceptance_flag": "REJECTED",
            }]
        }


class LegacyMobileUsers(FakeUsers):
    def get_by_public_address(self, address):
        result = super().get_by_public_address(address)
        result["result"][0]["usage_flag"] = "UNKNOWN"
        result["result"][0]["guidelines_acceptance_flag"] = "UNKNOWN"
        return result


class FakeRewards:
    def __init__(self):
        self.documents = [
            {
                "_id": "value",
                "document_type": "brainstem_value_entitlement",
                "public_address": WALLET,
                "source": Source.brainstem,
                "status": "created",
                "amount": 3,
                "commit_id": "commit",
            },
            {
                "_id": "upload",
                "document_type": "brainstem_reward_eligibility",
                "public_address": WALLET,
                "source": Source.brainstem,
                "status": "created",
                "amount": 1,
                "reward_day": "2026-07-25",
                "reward_kind": "rest",
            },
        ]
        self.paid = []
        self.payout_claims = []

    def get_brainstem_payout_claims(self, _address):
        return deepcopy(self.payout_claims)

    def query_all(self, _query):
        return deepcopy(self.documents)

    def committed_brainstem_value_entitlement_ids(self, _documents):
        return {"value"}

    def get_claim_count(self, *_args):
        return 0

    def create_brainstem_payout_claim_once(self, _address, amount, entity_ids):
        assert amount == 3 * 10**18
        assert entity_ids == ["value"]
        return "claim", True, {}

    def update_claim_to_transferring(self, *_args, **_kwargs):
        return None

    def update_claim_as_successful(self, *_args, **_kwargs):
        return None

    def mark_brainstem_eligibility_paid(self, entity_id, claim_id):
        self.paid.append((entity_id, claim_id))

    def update_claim_to_failed(self, *_args):
        raise AssertionError("a generated value claim must not fail")


def test_finalized_value_can_be_claimed_after_withdrawal_without_upload_reward(
    monkeypatch,
):
    rewards = FakeRewards()
    monkeypatch.setattr(claim_module, "user_dao", FakeUsers())
    monkeypatch.setattr(claim_module, "rewards_dao", rewards)
    monkeypatch.setattr(calculate_module, "rewards_dao", rewards)
    monkeypatch.setattr(
        claim_module,
        "config",
        {
            "rewards": {
                "account_private_key": PRIVATE_KEY,
                "token_contract_address": "0x" + "2" * 40,
            }
        },
    )
    command = ClaimRewardCommand(
        WALLET,
        Source.brainstem,
        expected_amount_raw=str(3 * 10**18),
        expected_eligibility_commitment_sha256=brainstem_reward_commitment(
            3 * 10**18, ["value"]
        ),
    )
    command.transfer = lambda amount, claim_id: "0x" + "3" * 64

    transaction_hash = command.execute()

    assert command.successful is True
    assert transaction_hash == "0x" + "3" * 64
    assert rewards.paid == [("value", "claim")]


def test_retry_returns_todays_success_without_another_transfer(monkeypatch):
    rewards = FakeRewards()
    transaction_hash = "0x" + "5" * 64
    rewards.payout_claims.append({
        "_id": "claim",
        "document_type": "reward_payout_claim",
        "status": "transfer_succeeded",
        "claim_day": datetime.utcnow().date().isoformat(),
        "transaction_hash": transaction_hash,
        "entity_ids": ["value"],
    })
    monkeypatch.setattr(claim_module, "user_dao", FakeUsers())
    monkeypatch.setattr(claim_module, "rewards_dao", rewards)
    monkeypatch.setattr(calculate_module, "rewards_dao", rewards)
    command = ClaimRewardCommand(WALLET, Source.brainstem)
    command.transfer = lambda *_args: (_ for _ in ()).throw(
        AssertionError("a retry must not transfer")
    )

    assert command.execute() == transaction_hash
    assert command.successful is True


def test_read_only_preview_matches_consent_filtered_claim_without_identifiers():
    rewards = FakeRewards()

    preview = preview_brainstem_claim(
        WALLET,
        FakeUsers(),
        rewards,
        datetime(2026, 8, 24),
    )

    assert preview["claimable"] is True
    assert preview["amountRaw"] == str(3 * 10**18)
    assert preview["amountTokens"] == "3"
    assert preview["eligibilityCount"] == 1
    assert preview["eligibilityCommitmentSha256"]
    assert preview["checkedAt"] == "2026-08-24T00:00:00Z"
    assert "value" not in str(preview)
    assert preview["broadcast"] is False


def test_read_only_preview_keeps_legacy_mobile_upload_rewards_claimable():
    preview = preview_brainstem_claim(
        WALLET,
        LegacyMobileUsers(),
        FakeRewards(),
        datetime(2026, 8, 24),
    )

    assert preview["claimable"] is True
    assert preview["amountRaw"] == str(4 * 10**18)
    assert preview["eligibilityCount"] == 2


def test_read_only_preview_blocks_an_unresolved_payout():
    rewards = FakeRewards()
    rewards.payout_claims.append({"status": "transferring"})

    preview = preview_brainstem_claim(
        WALLET,
        FakeUsers(),
        rewards,
        datetime(2026, 8, 24),
    )

    assert preview["claimable"] is False
    assert preview["blocker"] == "reconciliation_required"
    assert preview["broadcast"] is False


def test_claim_rejects_a_stale_confirmed_amount_before_creating_payout(monkeypatch):
    rewards = FakeRewards()
    monkeypatch.setattr(claim_module, "user_dao", FakeUsers())
    monkeypatch.setattr(claim_module, "rewards_dao", rewards)
    monkeypatch.setattr(calculate_module, "rewards_dao", rewards)
    command = ClaimRewardCommand(
        WALLET,
        Source.brainstem,
        expected_amount_raw=str(2 * 10**18),
        expected_eligibility_commitment_sha256=brainstem_reward_commitment(
            2 * 10**18, ["value"]
        ),
    )
    command.transfer = lambda *_args: (_ for _ in ()).throw(
        AssertionError("a stale confirmation must not transfer")
    )

    assert command.execute() is None
    assert command.successful is False
    assert command.messages == [ClaimRewardErrorMessages.AMOUNT_CHANGED]
    assert rewards.paid == []


def test_claim_rejects_a_non_string_confirmed_amount():
    try:
        ClaimRewardCommand(WALLET, Source.brainstem, expected_amount_raw=1)
    except ValueError as error:
        assert str(error) == "expected_amount_raw must be a decimal string"
    else:
        raise AssertionError("integer amounts can lose precision in clients")

    try:
        ClaimRewardCommand(
            WALLET,
            Source.brainstem,
            expected_amount_raw=str(3 * 10**18),
        )
    except ValueError as error:
        assert "must be provided together" in str(error)
    else:
        raise AssertionError("partial confirmation must not be accepted")


def test_claim_rejects_a_changed_eligibility_set_with_the_same_amount(monkeypatch):
    rewards = FakeRewards()
    monkeypatch.setattr(claim_module, "user_dao", FakeUsers())
    monkeypatch.setattr(claim_module, "rewards_dao", rewards)
    monkeypatch.setattr(calculate_module, "rewards_dao", rewards)
    command = ClaimRewardCommand(
        WALLET,
        Source.brainstem,
        expected_amount_raw=str(3 * 10**18),
        expected_eligibility_commitment_sha256=brainstem_reward_commitment(
            3 * 10**18, ["different-eligibility"]
        ),
    )
    command.transfer = lambda *_args: (_ for _ in ()).throw(
        AssertionError("changed eligibility must not transfer")
    )

    assert command.execute() is None
    assert command.successful is False
    assert command.messages == [ClaimRewardErrorMessages.ELIGIBILITY_CHANGED]
    assert rewards.paid == []
