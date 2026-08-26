import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def design_docs(name):
    return {
        item["_id"]: item
        for item in json.loads(
            (ROOT / "helpers" / "db_setup" / name).read_text()
        )["views"]
    }


def test_brainstem_reward_view_has_a_valid_status_key_and_value():
    reward_status = design_docs("metadata_views.json")["_design/reward-status"]
    source = reward_status["views"]["brainstem"]["map"]
    assert "doc[\"file_type\"], doc[\"reward_status\"] || 'unpaid'], value" in source
    assert "doc[\"file_type\"]], doc[\"reward_status\"]" not in source


def test_reward_history_view_matches_the_dao_path():
    rewards = design_docs("rewards_views.json")
    assert "_design/get-earning" not in rewards
    earning = rewards["_design/payouts"]["views"]["get-earning"]
    assert earning["reduce"] == "_sum"
    assert "doc[\"public_address\"]" in earning["map"]


def test_study_proposals_install_the_index_required_by_the_list_sort():
    from helpers.create_db import InitiateDB

    setup = json.loads(
        (ROOT / "helpers" / "db_setup" / "study_proposal_views.json").read_text()
    )
    assert setup["index"] == [
        {
            "index": {"fields": ["updatedAt"]},
            "name": "study-proposal-updated-at-index",
            "type": "json",
        }
    ]
    initiator = InitiateDB.__new__(InitiateDB)
    calls = []
    initiator.create_db = lambda database: calls.append(("database", database))
    initiator.create_from_file = lambda path, database: calls.append(
        (path, database)
    )
    initiator.create_studies_db()
    assert calls[-1][0] == "helpers/db_setup/study_proposal_views.json"


def test_existing_design_docs_are_updated_with_their_current_revision():
    from helpers.create_db import InitiateDB

    class Response:
        def __init__(self, status_code, data=None):
            self.status_code = status_code
            self._data = data or {}
            self.text = json.dumps(self._data)

        def json(self):
            return self._data

    class Client:
        def __init__(self):
            self.requests = []

        def document_url(self, database, document):
            return f"http://couch/{database}/{document}"

        def request(self, method, url, **kwargs):
            self.requests.append((method, url, kwargs))
            if method == "GET":
                return Response(200, {"_rev": "7-current"})
            return Response(201, {"ok": True})

    initiator = InitiateDB.__new__(InitiateDB)
    initiator.client = Client()
    initiator.rebuild_views = False
    initiator.create_views(
        "rewards",
        [{"_id": "_design/payouts", "views": {}, "language": "javascript"}],
    )

    method, url, kwargs = initiator.client.requests[-1]
    assert method == "PUT"
    assert url.endswith("/rewards/_design/payouts")
    assert json.loads(kwargs["data"])["_rev"] == "7-current"
