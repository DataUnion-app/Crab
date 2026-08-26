import json

import pytest

from commands.dataunions.brainstem.participant_projection import (
    BrainstemFilterSpec,
    participant_selector,
    project_participants,
)


def user(doc_id, amount, consent="ACCEPTED", gender="female", year=1990):
    return {
        "_id": doc_id,
        "public_address": f"wallet-{doc_id}",
        "rewards": 999,
        "usage_flag": consent,
        "guidelines_acceptance_flag": consent,
        "metadata": {"gender": gender, "year": year, "region": "Europe"},
        "recording_data": {
            "total_amount": amount,
            "total_rows": amount * 10,
            "total_durations": amount * 100,
            "counts": {"rest": amount},
            "durations": {"rest": amount * 100},
            "rows": {"rest": amount * 10},
            "private_extension": {"wallet": "must-not-leak"},
        },
    }


def test_projection_never_returns_rows_or_exact_counts():
    result = project_participants(
        [user(str(index), index + 1) for index in range(20)],
        BrainstemFilterSpec(page=0, per_page=2),
    )

    assert result == {
        "rows": [],
        "participantCount": "20_or_more",
        "participantRowsExposed": False,
    }


def test_public_projection_has_no_identifiers_metrics_or_rewards():
    result = project_participants(
        [user("internal-id", 2)], BrainstemFilterSpec()
    )
    encoded = json.dumps(result)

    assert result["rows"] == []
    assert result["participantCount"] == "fewer_than_20"
    for forbidden in ("public_address", "wallet-internal-id", "rewards", "internal-id"):
        assert forbidden not in encoded


def test_both_consent_flags_are_enforced():
    partially_consented = user("partial", 5)
    partially_consented["guidelines_acceptance_flag"] = "REJECTED"
    result = project_participants([partially_consented], BrainstemFilterSpec())
    assert result["participantCount"] == "fewer_than_20"
    assert result["rows"] == []


def test_recording_type_filter_excludes_users_without_that_recording():
    rest_user = user("rest", 1)
    sleep_user = user("sleep", 2)
    sleep_user["recording_data"]["counts"] = {"sleep": 2}

    result = project_participants(
        [rest_user, sleep_user],
        BrainstemFilterSpec(recording_type="rest", min_amount=0),
    )

    assert result["participantCount"] == "fewer_than_20"
    assert result["rows"] == []


def test_database_selector_uses_the_same_filter_dimensions():
    spec = BrainstemFilterSpec(
        recording_type="rest", min_age=20, max_age=40,
        gender="female", ethnicity="Europe", min_amount=2, max_amount=8,
    )
    assert participant_selector(spec, current_year=2026) == {
        "recording_data": {"$exists": True},
        "usage_flag": "ACCEPTED",
        "guidelines_acceptance_flag": "ACCEPTED",
        "metadata.year": {"$gte": 1986, "$lte": 2006},
        "recording_data.counts.rest": {"$gte": 2, "$lte": 8},
        "metadata.gender": "female",
        "metadata.region": "Europe",
    }


@pytest.mark.parametrize(
    "changes",
    [
        {"page": -1},
        {"per_page": 101},
        {"sort_by": "public_address"},
        {"sort_direction": "sideways"},
        {"min_age": 50, "max_age": 20},
    ],
)
def test_invalid_filter_contract_is_rejected(changes):
    with pytest.raises(ValueError):
        BrainstemFilterSpec(**changes)
