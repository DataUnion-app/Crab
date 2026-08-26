from dao.user_mutations import with_username


def test_username_update_preserves_account_and_consent_fields():
    original = {
        "_id": "user-1",
        "public_address": "0xA",
        "nonce": 123,
        "status": "NEW",
        "is_access_blocked": False,
        "usage_flag": "ACCEPTED",
        "guidelines_acceptance_flag": "REJECTED",
        "claims": ["User"],
    }
    updated = with_username(original, "brainstem_user")

    assert updated["username"] == "brainstem_user"
    for field in (
        "public_address",
        "nonce",
        "status",
        "is_access_blocked",
        "usage_flag",
        "guidelines_acceptance_flag",
        "claims",
    ):
        assert updated[field] == original[field]
    assert "username" not in original
