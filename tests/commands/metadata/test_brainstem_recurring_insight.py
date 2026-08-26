from copy import deepcopy

import pytest
from eth_account import Account
from eth_account.messages import encode_defunct

from commands.dataunions.brainstem.personal_insight import LEGACY_POLICY
from commands.dataunions.brainstem.recurring_insight import (
    RecurringInsightError,
    apply_signed_action,
    claim_due,
    complete_lease,
    create_challenge,
    due,
    result_expires_at,
    renewal_state,
)


NOW = 1_800_000_000
ORIGIN = "https://desci.example"
ACCOUNT = Account.from_key("0x" + "55" * 32)
DIGEST = "sha256:" + "6" * 64
SETTINGS = {
    "cadenceDays": 7,
    "maximumRunsPer30Days": 4,
    "maximumChargeMinor": 0,
    "currency": "none",
    "notification": "in_app",
    "retentionDays": 14,
    "minimumNewRecordings": 1,
    "startsAt": NOW,
    "expiresAt": NOW + 365 * 86400,
    "entitlement": "no_charge",
}


def challenge(action, current=None):
    return create_challenge(
        user_id="participant-1",
        address=ACCOUNT.address,
        origin=ORIGIN,
        action=action,
        policy=LEGACY_POLICY,
        algorithm_image_digest=DIGEST,
        settings=SETTINGS,
        current=current,
        now=NOW,
        challenge_id_factory=lambda: "c" * 32,
        nonce_factory=lambda: "n" * 43,
    )


def apply(value, action, current=None, now=NOW + 1):
    signature = Account.sign_message(
        encode_defunct(text=value["message"]), ACCOUNT.key
    ).signature.hex()
    return apply_signed_action(
        value,
        current,
        user_id="participant-1",
        address=ACCOUNT.address,
        origin=ORIGIN,
        action=action,
        signature=signature,
        now=now,
    )


def active():
    _consumed, authorization = apply(challenge("activate"), "activate")
    return authorization


def test_standing_consent_is_signed_separate_bounded_and_default_off():
    authorization = active()
    assert authorization["state"] == "active"
    assert authorization["settings"] == SETTINGS
    assert due(
        authorization,
        feature_enabled=False,
        current_data_consent=True,
        latest_source_accepted_at=NOW + 2,
        new_eligible_recordings=1,
        now=NOW + 3,
    ) == (False, "feature_disabled")
    assert due(
        authorization,
        feature_enabled=True,
        current_data_consent=True,
        latest_source_accepted_at=NOW + 2,
        new_eligible_recordings=1,
        now=NOW + 3,
    ) == (True, "due")


def test_pause_resume_revoke_delete_and_tampering_fail_closed():
    authorization = active()
    pause = challenge("pause", authorization)
    _consumed, paused = apply(pause, "pause", authorization)
    assert paused["state"] == "paused"
    resume = challenge("resume", paused)
    _consumed, resumed = apply(resume, "resume", paused)
    assert resumed["state"] == "active"

    tampered = deepcopy(challenge("revoke", resumed))
    tampered["settings"]["maximumRunsPer30Days"] = 31
    with pytest.raises(RecurringInsightError):
        apply(tampered, "revoke", resumed)

    revoke = challenge("revoke", resumed)
    _consumed, revoked = apply(revoke, "revoke", resumed)
    assert revoked["state"] == "revoked"

    fresh = active()
    delete = challenge("delete", fresh)
    _consumed, tombstone = apply(delete, "delete", fresh)
    assert tombstone["state"] == "deleted"
    assert "userId" not in tombstone
    assert "settings" not in tombstone


def test_version_drift_and_budget_require_explicit_control():
    authorization = active()
    changed = renewal_state(
        authorization, LEGACY_POLICY, "sha256:" + "7" * 64
    )
    assert changed["state"] == "renewal_required"
    assert due(
        changed,
        feature_enabled=True,
        current_data_consent=True,
        latest_source_accepted_at=NOW + 2,
        new_eligible_recordings=1,
        now=NOW + 3,
    ) == (False, "renewal_required")
    renewal = challenge("activate", changed)
    _consumed, renewed = apply(renewal, "activate", changed)
    assert renewal["targetAuthorizationSha256"]
    assert renewed["state"] == "active"
    assert renewed["revision"] == changed["revision"] + 1

    _consumed, paused = apply(
        challenge("pause", authorization), "pause", authorization
    )
    changed_while_paused = renewal_state(
        paused, LEGACY_POLICY, "sha256:" + "7" * 64
    )
    assert changed_while_paused["state"] == "renewal_required"
    with pytest.raises(RecurringInsightError, match="authorization_not_paused"):
        apply(
            challenge("resume", changed_while_paused),
            "resume",
            changed_while_paused,
        )

    authorization["lastRunAt"] = NOW
    authorization["lastSourceAcceptedAt"] = NOW
    authorization["runs"] = [NOW - offset for offset in (1, 2, 3, 4)]
    assert due(
        authorization,
        feature_enabled=True,
        current_data_consent=True,
        latest_source_accepted_at=NOW + 1,
        new_eligible_recordings=1,
        now=NOW + 8 * 86400,
    ) == (False, "budget")


def test_atomic_lease_retry_notification_and_retention_contract():
    authorization = active()
    claimed, capability, reason = claim_due(
        authorization,
        lease_id="l" * 43,
        feature_enabled=True,
        current_data_consent=True,
        latest_source_accepted_at=NOW + 1,
        new_eligible_recordings=1,
        now=NOW + 2,
    )
    assert reason == "claimed"
    duplicate, no_capability, reason = claim_due(
        claimed,
        lease_id="m" * 43,
        feature_enabled=True,
        current_data_consent=True,
        latest_source_accepted_at=NOW + 1,
        new_eligible_recordings=1,
        now=NOW + 3,
    )
    assert duplicate == claimed
    assert no_capability is None
    assert reason == "leased"

    retried, retry_capability, reason = claim_due(
        claimed,
        lease_id="m" * 43,
        feature_enabled=True,
        current_data_consent=True,
        latest_source_accepted_at=NOW + 1,
        new_eligible_recordings=1,
        now=NOW + 303,
    )
    assert reason == "claimed"
    assert retry_capability["runKey"] == capability["runKey"]
    completed, notification = complete_lease(
        retried, retry_capability["lease"], completed_at=NOW + 304
    )
    assert notification["message"] == "Your updated Insight is ready."
    assert "userId" not in notification
    assert result_expires_at(completed, NOW + 304) == NOW + 304 + 14 * 86400


def test_expiry_data_change_and_zero_run_budget_are_fail_closed():
    authorization = active()
    assert due(
        authorization,
        feature_enabled=True,
        current_data_consent=True,
        latest_source_accepted_at=NOW + 1,
        new_eligible_recordings=0,
        now=NOW + 2,
    ) == (False, "insufficient_data_change")
    assert due(
        authorization,
        feature_enabled=True,
        current_data_consent=True,
        latest_source_accepted_at=NOW + 1,
        new_eligible_recordings=1,
        now=SETTINGS["expiresAt"],
    ) == (False, "expired")
    authorization["settings"]["maximumRunsPer30Days"] = 0
    assert due(
        authorization,
        feature_enabled=True,
        current_data_consent=True,
        latest_source_accepted_at=NOW + 1,
        new_eligible_recordings=1,
        now=NOW + 2,
    ) == (False, "budget")
