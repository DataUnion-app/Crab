import pytest

from dao.base_dao import BaseDao, DBResultError
from dao.couchdb_client import CouchDBClient


class FakeSession:
    def __init__(self):
        self.auth = None
        self.headers = {}
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        return object()


class FakeResponse:
    def __init__(self, status_code, document=None, text=""):
        self.status_code = status_code
        self._document = document or {}
        self.text = text

    def json(self):
        return self._document


class FakeClient:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []

    def document_url(self, database, document_id):
        return f"http://couch/{database}/{document_id}"

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        return next(self.responses)


def test_client_keeps_credentials_out_of_urls_and_applies_timeouts():
    session = FakeSession()
    client = CouchDBClient(
        "user", "secret", "couch:5984", 1.5, 9, session=session
    )

    url = client.document_url("users", "record:1")
    client.request("GET", url)

    assert url == "http://couch:5984/users/record:1"
    assert "user:secret@" not in url
    assert session.auth == ("user", "secret")
    assert session.calls[0][2]["timeout"] == (1.5, 9)


def test_mutation_rereads_and_recomputes_after_conflict():
    client = FakeClient([
        FakeResponse(200, {"_id": "u", "_rev": "1-a", "value": 1}),
        FakeResponse(409, text="conflict"),
        FakeResponse(200, {"_id": "u", "_rev": "2-b", "value": 2}),
        FakeResponse(201, {"ok": True, "id": "u", "rev": "3-c"}),
    ])
    dao = BaseDao()
    dao.db_name = "users"
    dao.client = client

    result = dao.mutate_doc(
        "u", lambda document: {**document, "value": document["value"] + 1}
    )

    assert result["rev"] == "3-c"
    put_bodies = [call[2]["data"] for call in client.calls if call[0] == "PUT"]
    assert '"value": 2' in put_bodies[0]
    assert '"value": 3' in put_bodies[1]


def test_optional_read_distinguishes_missing_document_from_storage_failure():
    client = FakeClient(
        [
            FakeResponse(404, text="missing"),
            FakeResponse(503, text="unavailable"),
        ]
    )
    dao = BaseDao()
    dao.db_name = "users"
    dao.client = client

    assert dao.get_if_exists("missing") == (False, None)
    with pytest.raises(DBResultError, match="unavailable"):
        dao.get_if_exists("unavailable")
