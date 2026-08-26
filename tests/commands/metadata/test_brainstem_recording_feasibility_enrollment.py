from eth_account import Account
from eth_account.messages import encode_defunct
import pytest

from commands.dataunions.brainstem.recording_feasibility_enrollment import (
    CONSENT_CONTENT_SHA256,
    StudyEnrollmentError,
    apply_signed_action,
    candidate_action_challenge,
)
from commands.dataunions.brainstem.recording_feasibility_study import (
    protocol_sha256,
)


ACCOUNT = Account.from_key("0x" + "11" * 32)
ORIGIN = "https://desci.example"
NOW = 1785595200


def challenge(action="enroll", current=None, now=NOW):
    return candidate_action_challenge(
        user_id="participant-1",
        address=ACCOUNT.address,
        origin=ORIGIN,
        action=action,
        challenge_id="1" * 32,
        nonce="a" * 43,
        current=current,
        now=now,
    )


def sign(value):
    return Account.sign_message(
        encode_defunct(text=value["message"]), ACCOUNT.key
    ).signature.hex()


def apply(value, current=None, **overrides):
    signature = overrides.pop("signature", None)
    arguments = {
        "user_id": "participant-1",
        "address": ACCOUNT.address,
        "origin": ORIGIN,
        "action": value["action"],
        "signature": signature if signature is not None else sign(value),
        "has_current_data_consent": True,
        "now": NOW + 1,
    }
    arguments.update(overrides)
    return apply_signed_action(value, current, **arguments)


def test_exact_signed_enrollment_is_private_and_prospective():
    value = challenge()

    assert CONSENT_CONTENT_SHA256 in value["message"]
    assert protocol_sha256() in value["message"]
    consumed, enrollment, changed = apply(value)

    assert changed is True
    assert enrollment["state"] == "active"
    assert enrollment["enrolled_at"] == NOW + 1
    assert enrollment["assignment_starts_at"] == 1785628800
    assert enrollment["assignment_ends_at"] == 1786838400
    assert "address" not in enrollment
    assert "signature" not in enrollment
    assert "message" not in consumed
    assert "address" not in consumed
    assert "nonce" not in consumed


def test_enrollment_requires_current_general_consent():
    with pytest.raises(
        StudyEnrollmentError, match="current_data_consent_required"
    ):
        apply(challenge(), has_current_data_consent=False)


@pytest.mark.parametrize(
        ("field", "value"),
    [
        ("origin", "https://attacker.example"),
        ("chain_id", 1),
        ("protocol_sha256", "0" * 64),
        ("consent_content_sha256", "0" * 64),
        ("assignment_policy", "other"),
    ],
)
def test_any_signed_contract_substitution_fails(field, value):
    candidate = challenge()
    candidate[field] = value

    with pytest.raises(StudyEnrollmentError, match="challenge_unavailable"):
        apply(candidate)


def test_action_substitution_fails_against_the_target_enrollment():
    _consumed, enrollment, _changed = apply(challenge())
    candidate = challenge()
    candidate["action"] = "withdraw"

    with pytest.raises(StudyEnrollmentError, match="challenge_unavailable"):
        apply(candidate, enrollment)


def test_consumed_challenge_cannot_be_replayed():
    value = challenge()
    signature = sign(value)
    consumed, enrollment, _changed = apply(value, signature=signature)

    with pytest.raises(StudyEnrollmentError, match="challenge_unavailable"):
        apply(consumed, enrollment, signature=signature)


def test_same_version_enroll_and_withdraw_are_idempotent():
    _consumed, enrollment, _changed = apply(challenge())
    _consumed, repeated, changed = apply(challenge(), enrollment)
    assert repeated == enrollment
    assert changed is False

    withdrawal = challenge("withdraw", enrollment)
    _consumed, withdrawn, changed = apply(withdrawal, enrollment)
    assert withdrawn["state"] == "withdrawn"
    assert changed is True

    repeated_challenge = challenge("withdraw", withdrawn)
    _consumed, repeated_withdrawal, changed = apply(
        repeated_challenge, withdrawn
    )
    assert repeated_withdrawal == withdrawn
    assert changed is False

    with pytest.raises(StudyEnrollmentError, match="withdrawal_is_terminal"):
        apply(challenge(), withdrawn)


def test_withdrawal_does_not_depend_on_general_data_consent():
    _consumed, enrollment, _changed = apply(challenge())
    withdrawal = challenge("withdraw", enrollment)

    _consumed, withdrawn, changed = apply(
        withdrawal,
        enrollment,
        has_current_data_consent=False,
    )

    assert changed is True
    assert withdrawn["state"] == "withdrawn"


def test_no_unsigned_or_unknown_participant_transition_exists():
    with pytest.raises(StudyEnrollmentError, match="signature_invalid"):
        apply(challenge(), signature="0x" + "00" * 65)
    with pytest.raises(StudyEnrollmentError, match="not_enrolled"):
        apply(challenge(), action="withdraw")


def test_protocol_upgrade_does_not_block_withdrawal():
    _consumed, enrollment, _changed = apply(challenge())
    historical = dict(enrollment)
    historical["protocol_version"] = "0.9.0"
    historical["protocol_sha256"] = "1" * 64
    historical["consent_version"] = "0.9.0"
    historical["consent_content_sha256"] = "2" * 64
    withdrawal = challenge("withdraw", historical)

    _consumed, withdrawn, changed = apply(withdrawal, historical)

    assert changed is True
    assert withdrawn["state"] == "withdrawn"
