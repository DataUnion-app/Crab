#!/usr/bin/env python3
import argparse
from datetime import datetime, timezone
from decimal import Decimal
import json

from commands.dataunions.brainstem.consent import has_legacy_mobile_consent
from commands.dataunions.brainstem.record_projection import (
    has_unresolved_payout,
    rewards_allowed_by_consent,
)
from commands.rewards.calculate_reward import (
    brainstem_reward_commitment,
    calculate_brainstem_reward_amount,
)
from models.metadata.metadata_models import Source
from models.rewards.rewards_model import RewardStatus, safe_reward_failure_message


def preview_brainstem_claim(public_address, users, rewards, now=None):
    now = now or datetime.now(timezone.utc)
    now = (
        now.replace(tzinfo=timezone.utc)
        if now.tzinfo is None
        else now.astimezone(timezone.utc)
    )
    result = {
        "schema": "brainstem.reward-claim-preview/v1",
        "wallet": public_address,
        "checkedAt": now.replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "claimDay": now.date().isoformat(),
        "claimable": False,
        "blocker": None,
        "amountRaw": "0",
        "amountTokens": "0",
        "eligibilityCount": 0,
        "eligibilityCommitmentSha256": None,
        "broadcast": False,
    }
    matching_users = users.get_by_public_address(public_address).get("result", [])
    if len(matching_users) != 1:
        result["blocker"] = "brainstem_user_not_found"
        return result

    payout_claims = rewards.get_brainstem_payout_claims(public_address)
    if any(
        claim.get("status") == RewardStatus.TRANSFER_SUCCEEDED
        and claim.get("claim_day") == result["claimDay"]
        and claim.get("transaction_hash")
        for claim in payout_claims
    ):
        result["blocker"] = "already_claimed_today"
        return result
    if has_unresolved_payout(payout_claims):
        result["blocker"] = "reconciliation_required"
        return result
    if rewards.get_claim_count(now, Source.brainstem, public_address) >= 1:
        result["blocker"] = "daily_limit_reached"
        return result

    documents = rewards.query_all({
        "selector": {"public_address": public_address, "source": Source.brainstem}
    })
    documents = rewards_allowed_by_consent(
        documents, has_legacy_mobile_consent(matching_users[0])
    )
    amount, entity_ids = calculate_brainstem_reward_amount(
        public_address, documents, rewards
    )
    result["amountRaw"] = str(amount)
    result["amountTokens"] = format(Decimal(amount) / Decimal(10**18), "f")
    result["eligibilityCount"] = len(entity_ids)
    if not amount or not entity_ids:
        result["blocker"] = "nothing_to_claim"
        return result
    result["eligibilityCommitmentSha256"] = brainstem_reward_commitment(
        amount, entity_ids
    )
    result["claimable"] = True
    return result


def main():
    parser = argparse.ArgumentParser(
        description="Read one Brainstem wallet's current claim eligibility without writing or broadcasting."
    )
    parser.add_argument("--wallet", required=True)
    args = parser.parse_args()

    from config import config
    from dao.rewards_dao import rewards_dao
    from dao.users_dao import user_dao
    from web3 import Web3

    try:
        wallet = Web3.to_checksum_address(args.wallet)
        result = preview_brainstem_claim(wallet, user_dao, rewards_dao)
        result.update({
            "network": config["rewards"].get("network", ""),
            "chainId": int(config["rewards"]["chain_id"]),
            "tokenContract": Web3.to_checksum_address(
                config["rewards"]["token_contract_address"]
            ),
            "tokenDecimals": 18,
        })
    except Exception as error:
        result = {
            "schema": "brainstem.reward-claim-preview/v1",
            "claimable": False,
            "broadcast": False,
            "error": safe_reward_failure_message(error),
        }
    print(json.dumps(result, sort_keys=True))
    raise SystemExit(0 if "error" not in result else 1)


if __name__ == "__main__":
    main()
