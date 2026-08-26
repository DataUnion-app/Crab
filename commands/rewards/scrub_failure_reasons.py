#!/usr/bin/env python3
import argparse
import json

from models.rewards.rewards_model import safe_reward_failure_message


def scrub_failure_reasons(dao, apply=False):
    documents = list(dao.iter_query({
        "selector": {"reason": {"$exists": True}},
        "fields": ["_id", "reason"],
    }))
    changes = [
        (document["_id"], safe_reward_failure_message(document.get("reason")))
        for document in documents
        if safe_reward_failure_message(document.get("reason"))
        != document.get("reason")
    ]
    if apply:
        for document_id, safe_reason in changes:
            def replace_reason(document, value=safe_reason):
                document["reason"] = value
                return document

            dao.mutate_doc(document_id, replace_reason)
    return {
        "examined": len(documents),
        "changed": len(changes),
        "applied": bool(apply),
    }


def main():
    from dao.rewards_dao import rewards_dao

    parser = argparse.ArgumentParser(
        description="Redact credentials from stored reward failure reasons."
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Persist redactions. Without this flag the command is read-only.",
    )
    args = parser.parse_args()
    print(json.dumps(
        scrub_failure_reasons(rewards_dao, apply=args.apply), sort_keys=True
    ))


if __name__ == "__main__":
    main()
