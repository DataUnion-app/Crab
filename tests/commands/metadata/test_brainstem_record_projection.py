from types import SimpleNamespace

from commands.dataunions.brainstem.record_projection import (
    brainstem_payout_business_key,
    can_reopen_failed_payout,
    exclude_successfully_paid_eligibilities,
    has_unresolved_payout,
    project_record_on_user,
    rewards_allowed_by_consent,
    select_claimable_eligibilities,
    successful_payout_pending_projection,
)


def summary(record_type="rest", rows=3, duration=3, recognized_payloads=("ecg",)):
    return SimpleNamespace(
        record_type=record_type, rows=rows, duration=duration,
        recognized_payloads=recognized_payloads,
    )


def test_user_projection_is_idempotent_and_preserves_consent():
    user = {
        "_id": "user",
        "usage_flag": "ACCEPTED",
        "guidelines_acceptance_flag": "ACCEPTED",
    }
    first, changed = project_record_on_user(user, "record-1", summary())
    second, replay_changed = project_record_on_user(first, "record-1", summary())

    assert changed is True
    assert replay_changed is False
    assert second["recording_data"]["total_amount"] == 1
    assert second["recording_data"]["total_rows"] == 3
    assert second["usage_flag"] == "ACCEPTED"
    assert second["guidelines_acceptance_flag"] == "ACCEPTED"


def test_unknown_only_record_does_not_change_participant_aggregates():
    user = {"_id": "user", "recording_data": {"total_amount": 4}}
    projected, changed = project_record_on_user(
        user, "unknown-record", summary(recognized_payloads=())
    )
    assert changed is False
    assert projected == user


def eligibility(doc_id, day, kind, amount=1):
    return {
        "_id": doc_id,
        "document_type": "brainstem_reward_eligibility",
        "created_at": doc_id,
        "reward_day": day,
        "reward_kind": kind,
        "amount": amount,
        "status": "created",
    }


def test_daily_caps_are_applied_when_eligibility_is_claimed():
    documents = [
        eligibility("rest-1", "2026-07-17", "rest"),
        eligibility("rest-2", "2026-07-17", "rest"),
        eligibility("exercise-1", "2026-07-17", "exercise", 2),
        eligibility("exercise-2", "2026-07-17", "exercise", 2),
        eligibility("exercise-3", "2026-07-17", "exercise", 3),
        eligibility("exercise-4", "2026-07-17", "exercise", 3),
        {"_id": "legacy", "amount": 4, "status": "created"},
    ]

    selected = select_claimable_eligibilities(documents)
    assert {item["_id"] for item in selected} == {
        "legacy",
        "rest-1",
        "exercise-1",
        "exercise-2",
        "exercise-3",
    }


def test_paid_daily_slots_prevent_leftovers_rolling_into_later_claims():
    first = eligibility("rest-1", "2026-07-17", "rest")
    first["status"] = "paid"
    selected = select_claimable_eligibilities([
        first,
        eligibility("rest-2", "2026-07-17", "rest"),
        eligibility("rest-next-day", "2026-07-18", "rest"),
    ])
    assert [document["_id"] for document in selected] == ["rest-next-day"]


def test_legacy_reward_consumes_the_matching_daily_slot_during_migration():
    legacy = {
        "_id": "legacy-rest",
        "created_at": "2026-07-17T08:00:00",
        "task_type": "BRA_COMP_REST",
        "amount": 1,
        "status": "created",
    }

    selected = select_claimable_eligibilities([
        legacy,
        eligibility("new-rest", "2026-07-17", "rest"),
        eligibility("next-rest", "2026-07-18", "rest"),
    ])

    assert [document["_id"] for document in selected] == [
        "legacy-rest", "next-rest"
    ]


def test_paid_legacy_reward_keeps_the_migration_slot_consumed():
    legacy = {
        "_id": "legacy-rest",
        "created_at": "2026-07-17T08:00:00",
        "task_type": "BRA_COMP_REST",
        "amount": 1,
        "status": "paid",
    }

    selected = select_claimable_eligibilities([
        legacy, eligibility("new-rest", "2026-07-17", "rest")
    ])

    assert selected == []


def test_legacy_exercise_amount_consumes_each_inferred_slot():
    legacy = {
        "_id": "legacy-exercise",
        "created_at": "2026-07-17T08:00:00",
        "task_type": "BRA_COMP_BREATH_S",
        "amount": 6,
        "status": "created",
    }

    selected = select_claimable_eligibilities([
        legacy, eligibility("new-exercise", "2026-07-17", "exercise", 2)
    ])

    assert [document["_id"] for document in selected] == ["legacy-exercise"]


def test_successful_payout_is_authoritative_when_eligibility_projection_lags():
    documents = [
        eligibility("already-paid", "2026-07-17", "rest"),
        eligibility("new", "2026-07-18", "rest"),
    ]
    payout_claims = [{
        "status": "transfer_succeeded",
        "entity_ids": ["already-paid"],
    }]

    remaining = exclude_successfully_paid_eligibilities(documents, payout_claims)
    assert [document["_id"] for document in remaining] == ["new"]


def test_only_ambiguous_or_active_payouts_require_reconciliation():
    assert has_unresolved_payout([{"status": "transferring"}]) is True
    assert has_unresolved_payout([
        {"status": "failed", "transaction_hash": "0xabc"}
    ]) is True
    assert has_unresolved_payout([{"status": "failed"}]) is False
    assert has_unresolved_payout([{"status": "transfer_succeeded"}]) is False


def test_completed_payout_is_found_when_paid_projection_lags():
    claim = {
        "_id": "claim-1",
        "status": "transfer_succeeded",
        "transaction_hash": "0xabc",
        "entity_ids": ["already-paid"],
    }
    assert successful_payout_pending_projection(
        [eligibility("already-paid", "2026-07-17", "rest")], [claim]
    ) == claim
    assert successful_payout_pending_projection(
        [eligibility("new", "2026-07-18", "rest")], [claim]
    ) is None


def test_only_pre_broadcast_failures_are_automatically_reopened():
    assert can_reopen_failed_payout({"status": "failed"}) is True
    assert can_reopen_failed_payout({"status": "transfer_failed"}) is True
    assert can_reopen_failed_payout({
        "status": "failed", "transaction_hash": "0xambiguous"
    }) is False
    assert can_reopen_failed_payout({"status": "transferring"}) is False


def test_payout_business_key_is_wallet_and_day_not_observed_entity_set():
    key = brainstem_payout_business_key("0xAbC", "2026-07-17")
    assert key == brainstem_payout_business_key("0xabc", "2026-07-17")
    assert key != brainstem_payout_business_key("0xabc", "2026-07-18")


def test_value_requires_atomic_commit_and_is_not_subject_to_upload_caps():
    value = {
        "_id": "value-1",
        "document_type": "brainstem_value_entitlement",
        "status": "created",
        "amount": 3,
    }
    assert select_claimable_eligibilities([value]) == []
    assert select_claimable_eligibilities(
        [value], committed_value_ids={"value-1"}
    ) == [value]


def test_withdrawal_preserves_only_finalized_value_class_for_claiming():
    documents = [
        eligibility("upload", "2026-07-25", "rest"),
        {
            "_id": "value",
            "document_type": "brainstem_value_entitlement",
            "status": "created",
        },
        {
            "_id": "payout",
            "document_type": "reward_payout_claim",
            "status": "transfer_succeeded",
        },
        {"_id": "legacy", "status": "created", "amount": 1},
    ]

    assert rewards_allowed_by_consent(documents, True) == documents
    assert [
        document["_id"]
        for document in rewards_allowed_by_consent(documents, False)
    ] == ["value", "payout"]
