from copy import deepcopy
from datetime import datetime, timezone

import pytest
from eth_account import Account
from eth_account.messages import encode_defunct
from flask import Flask

from commands.users.participant_auth import ParticipantAuthService, SCOPE
from dao.sessions_dao import (
    MAX_ACTIVE_PARTICIPANT_CHALLENGES,
    ParticipantSessionStateError,
    SessionsDao,
)
from routes import participant_auth_routes as route_module


ORIGIN = "http://127.0.0.1:3000"
PRIVATE_KEY = "0x" + "11" * 32
ACCOUNT = Account.from_key(PRIVATE_KEY)


class MemorySessions(SessionsDao):
    def __new__(cls):
        return object.__new__(cls)

    def __init__(self):
        self.documents = {}
        self.revision = 0

    @property
    def challenges(self):
        return {
            challenge_id: challenge
            for document in self.documents.values()
            for challenge_id, challenge in document.get("challenges", {}).items()
        }

    @property
    def sessions(self):
        return {
            doc_id: document
            for doc_id, document in self.documents.items()
            if doc_id.startswith("participant_session:")
        }

    def get_if_exists(self, doc_id):
        document = self.documents.get(doc_id)
        return (document is not None, deepcopy(document))

    def save(self, doc_id, data):
        self.revision += 1
        document = deepcopy(data)
        document["_rev"] = str(self.revision)
        self.documents[doc_id] = document
        return {"ok": True, "id": doc_id, "rev": document["_rev"]}

    def mutate_doc(self, doc_id, mutator, max_attempts=3):
        del max_attempts
        exists, document = self.get_if_exists(doc_id)
        if not exists:
            raise ParticipantSessionStateError("Document unavailable")
        updated = mutator(document)
        if updated is None:
            return document
        self.save(doc_id, updated)
        return updated


class MemoryUsers:
    def __init__(self):
        self.user = {
            "_id": "internal-participant",
            "public_address": ACCOUNT.address,
            "is_access_blocked": False,
            "usage_flag": "ACCEPTED",
            "guidelines_acceptance_flag": "ACCEPTED",
        }

    def get_by_public_address(self, address):
        rows = [self.user] if address.lower() == ACCOUNT.address.lower() else []
        return {"result": deepcopy(rows)}

    def get_doc_by_id(self, user_id):
        if user_id != self.user["_id"]:
            raise KeyError(user_id)
        return deepcopy(self.user)


@pytest.fixture
def client(monkeypatch):
    now = [1_800_000_000]
    counter = iter(range(1, 100))
    secrets = iter("stuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ")
    sessions = MemorySessions()
    users = MemoryUsers()
    service = ParticipantAuthService(
        sessions,
        users,
        [ORIGIN],
        clock=lambda: now[0],
        nonce_factory=lambda: "n" * 43,
        id_factory=lambda: "{:032x}".format(next(counter)),
        secret_factory=lambda: next(secrets) * 43,
    )
    monkeypatch.setattr(route_module, "_service", lambda: service)
    app = Flask(__name__)
    app.register_blueprint(route_module.participant_auth_routes)
    return app.test_client(), now, sessions, users


def headers(origin=ORIGIN, token=None):
    value = {"X-Brainstem-Origin": origin}
    if token:
        value["Authorization"] = "Participant {}".format(token)
    return value


def create_challenge(http, address=ACCOUNT.address, origin=ORIGIN):
    return http.post(
        "/api/v1/participant-auth/challenges",
        json={"address": address},
        headers=headers(origin),
    )


def sign(message, private_key=PRIVATE_KEY):
    return Account.sign_message(
        encode_defunct(text=message), private_key=private_key
    ).signature.hex()


def create_session(http, challenge, signature=None, origin=ORIGIN):
    result = challenge.get_json()["result"]
    return http.post(
        "/api/v1/participant-auth/sessions",
        json={
            "challengeId": result["challengeId"],
            "address": ACCOUNT.address,
            "signature": signature or sign(result["message"]),
        },
        headers=headers(origin),
    )


def test_success_projects_only_minimal_status_and_logout(client):
    http, _now, _sessions, _users = client
    challenge = create_challenge(http)
    assert challenge.status_code == 201
    body = challenge.get_json()["result"]
    assert body["chainId"] == 11155420
    assert "cannot authorize a transaction" in body["message"]
    session = create_session(http, challenge)
    assert session.status_code == 201
    token = session.get_json()["result"]["token"]
    assert session.get_json()["result"]["scope"] == SCOPE

    status = http.get(
        "/api/v1/participant-auth/self-status", headers=headers(token=token)
    )
    assert status.status_code == 200
    projection = status.get_json()["result"]
    assert projection["consent"] == {
        "dataUse": "ACCEPTED",
        "guidelines": "ACCEPTED",
    }
    serialized = status.get_data(as_text=True)
    assert ACCOUNT.address not in serialized
    assert "internal-participant" not in serialized
    assert token not in serialized

    assert (
        http.delete(
            "/api/v1/participant-auth/session", headers=headers(token=token)
        ).status_code
        == 204
    )
    assert (
        http.get(
            "/api/v1/participant-auth/self-status", headers=headers(token=token)
        ).status_code
        == 401
    )


def test_session_replacement_does_not_remove_other_active_challenges(client):
    http, _now, sessions, _users = client
    first = create_challenge(http)
    repeated = create_challenge(http)
    assert repeated.get_json()["result"] != first.get_json()["result"]
    assert len(sessions.challenges) == 2

    first_session = create_session(http, repeated)
    first_token = first_session.get_json()["result"]["token"]
    second = create_challenge(http)
    second_session = create_session(http, second)
    second_token = second_session.get_json()["result"]["token"]
    assert second_token != first_token
    assert len(sessions.challenges) == 1
    assert len(sessions.sessions) == 1
    assert (
        http.get(
            "/api/v1/participant-auth/self-status",
            headers=headers(token=first_token),
        ).status_code
        == 401
    )


def test_invalid_signature_expiry_and_replay_fail_closed(client):
    http, now, _sessions, _users = client
    challenge = create_challenge(http)
    assert create_session(http, challenge, "0x" + "00" * 65).status_code == 401
    wrong_key = "0x" + "22" * 32
    assert create_session(http, challenge, sign(
        challenge.get_json()["result"]["message"], wrong_key
    )).status_code == 401

    valid = create_session(http, challenge)
    assert valid.status_code == 201
    assert create_session(http, challenge).status_code == 401

    expired = create_challenge(http)
    now[0] += 301
    assert create_session(http, expired).status_code == 410


def test_parallel_login_challenges_cannot_overwrite_each_other(client):
    http, _now, sessions, _users = client
    first = create_challenge(http)
    second = create_challenge(http)

    assert create_session(http, first).status_code == 201
    assert create_session(http, second).status_code == 201
    assert sessions.challenges == {}


def test_abandoned_challenges_are_bounded_without_replacing_active_ones(client):
    http, _now, sessions, _users = client
    challenges = [
        create_challenge(http)
        for _ in range(MAX_ACTIVE_PARTICIPANT_CHALLENGES + 1)
    ]

    assert len(sessions.challenges) == MAX_ACTIVE_PARTICIPANT_CHALLENGES
    assert create_session(http, challenges[-1]).status_code == 401
    assert create_session(http, challenges[0]).status_code == 201


def test_origin_scope_session_expiry_and_legacy_jwt_isolation(client):
    http, now, _sessions, _users = client
    assert create_challenge(http, origin="https://attacker.example").status_code == 403
    challenge = create_challenge(http)
    assert create_session(
        http, challenge, origin="https://attacker.example"
    ).status_code == 403
    session = create_session(http, challenge)
    token = session.get_json()["result"]["token"]
    assert (
        http.get(
            "/api/v1/participant-auth/self-status",
            headers=headers("https://attacker.example", token),
        ).status_code
        == 403
    )
    assert (
        http.get(
            "/api/v1/participant-auth/self-status",
            headers={
                "X-Brainstem-Origin": ORIGIN,
                "Authorization": "Bearer {}".format(token),
            },
        ).status_code
        == 401
    )
    now[0] += 901
    assert (
        http.get(
            "/api/v1/participant-auth/self-status", headers=headers(token=token)
        ).status_code
        == 401
    )


def test_unknown_and_blocked_users_are_rejected_only_after_signature(client):
    http, _now, _sessions, users = client
    unknown = Account.create()
    challenge = create_challenge(http, address=unknown.address)
    assert challenge.status_code == 201
    result = challenge.get_json()["result"]
    response = http.post(
        "/api/v1/participant-auth/sessions",
        json={
            "challengeId": result["challengeId"],
            "address": unknown.address,
            "signature": Account.sign_message(
                encode_defunct(text=result["message"]), unknown.key
            ).signature.hex(),
        },
        headers=headers(),
    )
    assert response.status_code == 401

    users.user["is_access_blocked"] = True
    blocked = create_challenge(http)
    assert create_session(http, blocked).status_code == 401
