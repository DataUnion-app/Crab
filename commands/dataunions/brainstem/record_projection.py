from copy import deepcopy
from datetime import datetime
import hashlib
import math
from types import SimpleNamespace

from commands.dataunions.brainstem.record_contract import CONTRACT_VERSION


def project_record_on_user(user, record_id, summary, metadata=None):
    """Apply one accepted record exactly once to a user aggregate document."""
    projected = deepcopy(user)
    applied_ids = list(projected.get("brainstem_record_ids", []))
    if record_id in applied_ids:
        return projected, False
    if not getattr(summary, "recognized_payloads", ("legacy",)):
        return projected, False

    recording_data = deepcopy(projected.get("recording_data", {}))
    recording_data.setdefault("total_amount", 0)
    recording_data.setdefault("total_rows", 0)
    recording_data.setdefault("total_durations", 0)
    recording_data.setdefault("counts", {})
    recording_data.setdefault("durations", {})
    recording_data.setdefault("rows", {})

    record_type = summary.record_type
    recording_data["total_amount"] += 1
    recording_data["total_rows"] += summary.rows
    recording_data["total_durations"] += summary.duration
    recording_data["counts"][record_type] = (
        recording_data["counts"].get(record_type, 0) + 1
    )
    recording_data["durations"][record_type] = (
        recording_data["durations"].get(record_type, 0) + summary.duration
    )
    recording_data["rows"][record_type] = (
        recording_data["rows"].get(record_type, 0) + summary.rows
    )

    projected["recording_data"] = recording_data
    projected["brainstem_record_ids"] = applied_ids + [record_id]
    if metadata and "metadata" not in projected:
        projected["metadata"] = deepcopy(metadata)
    return projected, True


def rebuild_brainstem_record_projection(user, record_documents):
    """Rebuild derived Brainstem counters from the surviving record documents."""
    projected = deepcopy(user)
    projected.pop("recording_data", None)
    projected.pop("brainstem_record_ids", None)
    for document in sorted(record_documents, key=lambda item: item.get("_id", "")):
        recognized_payloads = document.get("recognized_payloads")
        if (
            document.get("record_contract_version") != CONTRACT_VERSION
            or not isinstance(recognized_payloads, list)
            or not recognized_payloads
        ):
            continue
        record_id = document.get("_id")
        record_type = document.get("record_type")
        rows = document.get("rows")
        duration = document.get("duration")
        if (
            not isinstance(record_id, str)
            or not isinstance(record_type, str)
            or not isinstance(rows, (int, float))
            or isinstance(rows, bool)
            or not isinstance(duration, (int, float))
            or isinstance(duration, bool)
        ):
            continue
        summary = SimpleNamespace(
            record_type=record_type,
            rows=rows,
            duration=duration,
            recognized_payloads=tuple(recognized_payloads),
        )
        projected, _ = project_record_on_user(projected, record_id, summary)
    return projected


LEGACY_REWARD_SLOTS = {
    "BRA_COMP_REST": ("rest", 1),
    "BRA_COMP_SLEEP": ("sleep", 2),
    "BRA_COMP_BREATH_S": ("exercise", 2),
    "BRA_COMP_BREATH_L": ("exercise", 3),
}


def _legacy_reward_slots(document):
    mapping = LEGACY_REWARD_SLOTS.get(document.get("task_type"))
    created_at = document.get("created_at")
    if not mapping or not isinstance(created_at, str):
        return None
    try:
        reward_day = datetime.fromisoformat(
            created_at.replace("Z", "+00:00")
        ).date().isoformat()
    except ValueError:
        return None
    reward_kind, unit_amount = mapping
    amount = document.get("amount", 0)
    if not isinstance(amount, (int, float)) or isinstance(amount, bool) or amount <= 0:
        return None
    return reward_day, reward_kind, max(1, math.ceil(amount / unit_amount))


def rewards_allowed_by_consent(documents, has_current_consent):
    """Withdrawal preserves committed compute value, not record-upload rewards."""
    if has_current_consent:
        return list(documents)
    return [
        document
        for document in documents
        if document.get("document_type") in {
            "brainstem_value_entitlement",
            "reward_payout_claim",
        }
    ]


def select_claimable_eligibilities(
    documents, paid_entity_ids=None, committed_value_ids=None
):
    """Apply lifetime daily caps, including already-paid eligibility slots."""
    paid_entity_ids = set(paid_entity_ids or [])
    committed_value_ids = set(committed_value_ids or [])
    legacy = []
    eligibility = []
    value_entitlements = []
    for document in documents:
        if document.get("document_type") == "brainstem_reward_eligibility":
            eligibility.append(document)
        elif document.get("document_type") == "brainstem_value_entitlement":
            value_entitlements.append(document)
        else:
            if (
                document.get("status") == "created"
                and document.get("_id") not in paid_entity_ids
                and document.get("document_type") != "reward_payout_claim"
            ):
                legacy.append(document)

    caps = {"rest": 1, "sleep": 1, "exercise": 3}
    counts = {}
    for document in documents:
        if document.get("document_type") in {
            "brainstem_reward_eligibility", "reward_payout_claim"
        }:
            continue
        legacy_slots = _legacy_reward_slots(document)
        if legacy_slots is None:
            continue
        reward_day, reward_kind, slot_count = legacy_slots
        key = (reward_day, reward_kind)
        counts[key] = min(caps[reward_kind], counts.get(key, 0) + slot_count)

    selected = list(legacy)
    selected.extend(
        document
        for document in value_entitlements
        if document.get("status") == "created"
        and document.get("_id") in committed_value_ids
        and document.get("_id") not in paid_entity_ids
    )
    for document in sorted(
        eligibility, key=lambda item: (item.get("created_at", ""), item.get("_id", ""))
    ):
        key = (document.get("reward_day"), document.get("reward_kind"))
        cap = caps.get(document.get("reward_kind"), 0)
        if counts.get(key, 0) >= cap:
            continue
        counts[key] = counts.get(key, 0) + 1
        if (
            document.get("status") == "created"
            and document.get("_id") not in paid_entity_ids
        ):
            selected.append(document)
    return selected


def exclude_successfully_paid_eligibilities(documents, payout_claims):
    """Treat successful payout claims as authoritative if projections lag."""
    paid_ids = {
        entity_id
        for claim in payout_claims
        if claim.get("status") == "transfer_succeeded"
        for entity_id in claim.get("entity_ids", [])
    }
    return [document for document in documents if document.get("_id") not in paid_ids]


def has_unresolved_payout(payout_claims):
    """Block a new payout when the previous chain outcome needs reconciliation."""
    for claim in payout_claims:
        status = claim.get("status")
        if status in {"calculating", "transferring"}:
            return True
        if status in {"failed", "transfer_failed"} and claim.get("transaction_hash"):
            return True
    return False


def successful_payout_pending_projection(eligibility_documents, payout_claims):
    """Find a completed payout whose eligibility status still needs repair."""
    unpaid_ids = {document.get("_id") for document in eligibility_documents}
    for claim in payout_claims:
        if claim.get("status") != "transfer_succeeded":
            continue
        if unpaid_ids.intersection(claim.get("entity_ids", [])):
            return claim
    return None


def can_reopen_failed_payout(claim):
    """Only a known pre-broadcast failure is safe to retry automatically."""
    return (
        claim.get("status") in {"failed", "transfer_failed"}
        and not claim.get("transaction_hash")
    )


def brainstem_payout_business_key(public_address, claim_day):
    """One payout construction per wallet and UTC claim day."""
    return hashlib.sha256(
        f"{public_address.lower()}:{claim_day}".encode("utf-8")
    ).hexdigest()
