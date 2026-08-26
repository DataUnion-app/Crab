from copy import deepcopy

import pytest

from dao.study_dao import StudyDao, StudyStateSourceLimitError


DOTTED_OFFERING_ID = "brainstem.recording-feasibility.v1"


def test_materialization_states_uses_couch_safe_bounded_request_and_exact_key(
    monkeypatch,
):
    exact_active = {
        "user_id": "exact-active",
        "offerings": {
            DOTTED_OFFERING_ID: {"enrollment": {"state": "active"}}
        },
    }
    rows = [
        exact_active,
        {
            "user_id": "exact-withdrawn",
            "offerings": {
                DOTTED_OFFERING_ID: {
                    "enrollment": {"state": "withdrawn"}
                }
            },
        },
        {
            "user_id": "path-shaped-lookalike",
            "offerings": {
                "brainstem": {
                    "recording-feasibility": {
                        "v1": {"enrollment": {"state": "active"}}
                    }
                }
            },
        },
        {
            "user_id": "other-offering",
            "offerings": {
                "brainstem.other.v1": {
                    "enrollment": {"state": "active"}
                }
            },
        },
    ]
    captured = []
    dao = StudyDao()

    def query_data(query):
        captured.append(deepcopy(query))
        return {"result": deepcopy(rows)}

    monkeypatch.setattr(dao, "query_data", query_data)

    assert dao.materialization_states(DOTTED_OFFERING_ID, limit=10001) == [
        exact_active
    ]
    assert captured == [
        {
            "selector": {
                "document_type": "brainstem_study_participant_state"
            },
            "fields": ["user_id", "offerings"],
            "limit": 10001,
        }
    ]
    assert all(DOTTED_OFFERING_ID not in key for key in captured[0]["selector"])


def test_materialization_states_fails_closed_when_source_page_hits_limit(
    monkeypatch,
):
    dao = StudyDao()
    monkeypatch.setattr(
        dao,
        "query_data",
        lambda _query: {
            "result": [
                {"user_id": "source-{}".format(index), "offerings": {}}
                for index in range(10001)
            ]
        },
    )

    with pytest.raises(StudyStateSourceLimitError, match="source_limit_exceeded"):
        dao.materialization_states(DOTTED_OFFERING_ID, limit=10001)
