from commands.dataunions.brainstem.consent import (
    has_brainstem_data_consent,
    has_legacy_mobile_consent,
)


def test_both_consent_flags_are_required():
    assert has_brainstem_data_consent({
        "usage_flag": "ACCEPTED",
        "guidelines_acceptance_flag": "ACCEPTED",
    })
    assert not has_brainstem_data_consent({
        "usage_flag": "UNKNOWN",
        "guidelines_acceptance_flag": "ACCEPTED",
    })
    assert not has_brainstem_data_consent({
        "usage_flag": "ACCEPTED",
        "guidelines_acceptance_flag": "REJECTED",
    })
    assert not has_brainstem_data_consent({})


def test_legacy_mobile_operations_allow_unknown_but_not_rejection_or_blocking():
    assert has_legacy_mobile_consent({
        "usage_flag": "UNKNOWN",
        "guidelines_acceptance_flag": "UNKNOWN",
    })
    assert has_legacy_mobile_consent({
        "usage_flag": "ACCEPTED",
        "guidelines_acceptance_flag": "ACCEPTED",
    })
    assert not has_legacy_mobile_consent({
        "usage_flag": "REJECTED",
        "guidelines_acceptance_flag": "UNKNOWN",
    })
    assert not has_legacy_mobile_consent({
        "usage_flag": "UNKNOWN",
        "guidelines_acceptance_flag": "REJECTED",
    })
    assert not has_legacy_mobile_consent({"is_access_blocked": True})
    assert not has_legacy_mobile_consent({"profile": {}})
    assert not has_legacy_mobile_consent({
        "usage_flag": "INVALID",
        "guidelines_acceptance_flag": "UNKNOWN",
    })
    assert not has_legacy_mobile_consent({})
