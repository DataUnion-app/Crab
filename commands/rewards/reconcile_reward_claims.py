#!/usr/bin/env python3
import argparse
import json

from web3.exceptions import TransactionNotFound

from models.rewards.rewards_model import safe_reward_failure_message


def reconcile_reward_claims(dao, web3, apply=False):
    counts = {
        "examined": 0,
        "confirmedSuccessful": 0,
        "confirmedReverted": 0,
        "unresolved": 0,
        "withoutTransactionIdentity": 0,
        "applied": 0,
    }
    claims = dao.iter_query({
        "selector": {
            "document_type": "reward_payout_claim",
            "status": {
                "$in": ["calculating", "transferring", "failed", "transfer_failed"]
            },
        },
        "fields": ["_id", "status", "transaction_hash"],
    })
    for claim in claims:
        counts["examined"] += 1
        transaction_hash = claim.get("transaction_hash")
        if not transaction_hash:
            if claim.get("status") in {"calculating", "transferring"}:
                counts["withoutTransactionIdentity"] += 1
            continue
        try:
            receipt = web3.eth.get_transaction_receipt(transaction_hash)
        except TransactionNotFound:
            counts["unresolved"] += 1
            continue
        succeeded = int(receipt["status"]) == 1
        key = "confirmedSuccessful" if succeeded else "confirmedReverted"
        counts[key] += 1
        if apply:
            dao.reconcile_claim_receipt(
                claim["_id"], transaction_hash, succeeded
            )
            counts["applied"] += 1
    counts["applyRequested"] = bool(apply)
    counts["ok"] = (
        counts["unresolved"] == 0
        and counts["withoutTransactionIdentity"] == 0
    )
    return counts


def main():
    from web3 import HTTPProvider, Web3

    from config import config
    from dao.rewards_dao import rewards_dao

    parser = argparse.ArgumentParser(
        description="Reconcile only recorded Brainstem payout transaction hashes."
    )
    parser.add_argument(
        "--apply-confirmed",
        action="store_true",
        help="Apply confirmed success/revert receipts; unresolved claims stay blocked.",
    )
    args = parser.parse_args()
    web3 = Web3(HTTPProvider(
        config["rewards"]["network_url"],
        request_kwargs={
            "timeout": config["rewards"].getfloat("rpc_timeout_seconds", 30)
        },
    ))
    try:
        result = reconcile_reward_claims(
            rewards_dao, web3, apply=args.apply_confirmed
        )
    except Exception as error:
        result = {
            "schema": "brainstem.reward-reconciliation/v1",
            "ok": False,
            "error": safe_reward_failure_message(error),
        }
    else:
        result["schema"] = "brainstem.reward-reconciliation/v1"
    print(json.dumps(result, sort_keys=True))
    raise SystemExit(0 if result["ok"] else 1)


if __name__ == "__main__":
    main()
