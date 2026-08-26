from types import SimpleNamespace

import pytest
from flask import Flask

from commands.dataunions.brainstem.personal_insight import PersonalInsightError
from config import config
from routes import participant_auth_routes as route_module


ORIGIN = "http://127.0.0.1:3000"
NODE_TOKEN = "node-token-" + "n" * 32
GRANT = "1" * 32 + "." + "s" * 43
JOB = "a" * 64
RUN = "b" * 32
RESULT_SHA256 = "c" * 64
CAPABILITY = "2" * 32 + "." + "t" * 43
HISTORY = "d" * 64
ANALYSIS_ID = "brainstem.personal-resting-heart-overview/v1"


class FakeService:
    def __init__(self):
        self.calls = []

    def create_challenge(self, token, origin):
        self.calls.append(("challenge", token, origin))
        return {
            "challengeId": "1" * 32,
            "message": "fixed approval",
            "expiresAt": "2026-07-27T00:05:00Z",
            "chainId": 11155420,
            "method": "personal_sign",
        }

    def exchange(self, token, origin, challenge_id, signature):
        self.calls.append(("exchange", token, origin, challenge_id, signature))
        return {
            "grant": GRANT,
            "expiresAt": "2026-07-27T00:05:00Z",
            "scope": "participant:self:insight:run-once",
        }

    def claim(self, grant, job_id, run_id):
        self.calls.append(("claim", grant, job_id, run_id))
        return {"status": "claimed", "historyId": HISTORY}

    def history(self, token, origin, limit):
        self.calls.append(("history", token, origin, limit))
        return [
            {
                "historyId": HISTORY,
                "analysisId": "brainstem.personal-resting-heart-overview/v1",
                "algorithmVersion": "1.0.0",
                "algorithmImageDigest": "sha256:" + "2" * 64,
                "status": "complete",
                "createdAt": "2026-07-27T00:00:00Z",
                "completedAt": "2026-07-27T00:00:00Z",
                "expiresAt": "2026-08-10T00:00:00Z",
                "correctionState": "current",
                "updateAvailable": False,
            }
        ]

    def fetch(self, grant, job_id):
        self.calls.append(("fetch", grant, job_id))
        body = b'{"policy":"brainstem.personal-resting-rr/latest-16/v1","recordings":[],"schema":"brainstem.personal-resting-rr/v1"}'
        return SimpleNamespace(
            body=body,
            checksum="2" * 64,
        )

    def complete(self, grant, job_id, run_id, result_sha256):
        self.calls.append(
            ("complete", grant, job_id, run_id, result_sha256)
        )
        return {
            "status": "complete",
            "resultExpiresAt": "2026-08-10T00:00:00Z",
        }

    def revalidate(self, grant, job_id, run_id):
        self.calls.append(("revalidate", grant, job_id, run_id))
        return {"status": "authorized", "jobId": job_id, "runId": run_id}

    def revalidate_history(self, history_id):
        self.calls.append(("history_revalidate", history_id))
        return {"status": "authorized", "historyId": history_id}

    def issue_access(self, token, origin, grant, run_id, action):
        self.calls.append(
            ("access", token, origin, grant, run_id, action)
        )
        return {
            "capability": CAPABILITY,
            "runId": run_id,
            "action": action,
            "expiresAt": "2026-07-27T00:01:00Z",
        }

    def consume_access(self, capability, run_id, action):
        self.calls.append(("consume", capability, run_id, action))
        return {
            "status": "authorized",
            "runId": run_id,
            "action": action,
            "resultSha256": RESULT_SHA256 if action == "result" else None,
        }

    def issue_history_access(self, token, origin, history_id, action):
        self.calls.append(
            ("history_access", token, origin, history_id, action)
        )
        return {
            "capability": CAPABILITY,
            "historyId": history_id,
            "action": action,
            "expiresAt": "2026-07-27T00:01:00Z",
        }

    def consume_history_access(self, capability, history_id, action):
        self.calls.append(
            ("history_consume", capability, history_id, action)
        )
        return {
            "status": "authorized",
            "historyId": history_id,
            "action": action,
            "resultSha256": RESULT_SHA256 if action == "result" else None,
        }


@pytest.fixture
def client(monkeypatch):
    service = FakeService()
    monkeypatch.setattr(
        route_module, "_personal_service", lambda _analysis=ANALYSIS_ID: service
    )
    monkeypatch.setitem(
        config["brainstem_personal_insight"], "node_bearer_token", NODE_TOKEN
    )
    application = Flask(__name__)
    application.register_blueprint(route_module.participant_auth_routes)
    return application.test_client(), service


def participant_headers():
    return {
        "Authorization": "Participant participant-session",
        "X-Brainstem-Origin": ORIGIN,
    }


def node_headers(**extra):
    return {"Authorization": "Bearer {}".format(NODE_TOKEN), **extra}


def test_participant_challenge_and_exchange_are_narrow_and_no_store(client):
    http, service = client
    challenge = http.post(
        "/api/v1/participant-auth/personal-insights/resting-heart-overview/challenges",
        json={},
        headers=participant_headers(),
    )
    assert challenge.status_code == 201
    assert challenge.headers["Cache-Control"] == "private, no-store"
    challenge_id = challenge.get_json()["result"]["challengeId"]
    grant = http.post(
        "/api/v1/participant-auth/personal-insights/resting-heart-overview/grants",
        json={"challengeId": challenge_id, "signature": "0x" + "1" * 130},
        headers=participant_headers(),
    )
    assert grant.status_code == 201
    assert grant.get_json()["result"]["grant"] == GRANT
    assert [call[0] for call in service.calls] == ["challenge", "exchange"]

    assert (
        http.post(
            "/api/v1/participant-auth/personal-insights/resting-heart-overview/challenges",
            json={"algorithm": "caller-selected"},
            headers=participant_headers(),
        ).status_code
        == 400
    )


def test_only_dedicated_node_token_can_claim_or_fetch(client):
    http, service = client
    claim_url = "/api/v1/internal/personal-insights/grants/claim"
    body = {
        "analysisId": ANALYSIS_ID,
        "grant": GRANT,
        "jobId": JOB,
        "runId": RUN,
    }
    assert http.post(claim_url, json=body).status_code == 401
    assert (
        http.post(
            claim_url,
            json=body,
            headers={"Authorization": "Participant participant-session"},
        ).status_code
        == 401
    )
    assert service.calls == []

    claim = http.post(claim_url, json=body, headers=node_headers())
    assert claim.status_code == 200
    dataset = http.get(
        "/api/v1/internal/personal-insights/dataset",
        headers=node_headers(
            **{
                "X-Brainstem-Personal-Grant": GRANT,
                "X-Brainstem-Analysis-Id": ANALYSIS_ID,
                "X-Ocean-Compute-Job-Id": JOB,
            }
        ),
    )
    assert dataset.status_code == 200
    assert dataset.headers["X-Content-SHA256"] == "2" * 64
    assert dataset.headers["Cache-Control"] == "private, no-store"
    assert [call[0] for call in service.calls] == ["claim", "fetch"]


def test_completion_and_access_capability_routes_keep_secrets_server_side(client):
    http, service = client
    complete = http.post(
        "/api/v1/internal/personal-insights/runs/complete",
        json={
            "analysisId": ANALYSIS_ID,
            "grant": GRANT,
            "jobId": JOB,
            "runId": RUN,
            "resultSha256": RESULT_SHA256,
        },
        headers=node_headers(),
    )
    assert complete.status_code == 200

    revalidated = http.post(
        "/api/v1/internal/personal-insights/runs/revalidate",
        json={
            "analysisId": ANALYSIS_ID,
            "grant": GRANT,
            "jobId": JOB,
            "runId": RUN,
        },
        headers=node_headers(),
    )
    assert revalidated.status_code == 200
    assert revalidated.get_json() == {
        "result": {"status": "authorized", "jobId": JOB, "runId": RUN}
    }

    history_revalidated = http.post(
        "/api/v1/internal/personal-insights/history/revalidate",
        json={"analysisId": ANALYSIS_ID, "historyId": HISTORY},
        headers=node_headers(),
    )
    assert history_revalidated.status_code == 200
    assert history_revalidated.get_json() == {
        "result": {"status": "authorized", "historyId": HISTORY}
    }

    access = http.post(
        "/api/v1/participant-auth/personal-insights/runs/{}/access".format(RUN),
        json={
            "analysisId": ANALYSIS_ID,
            "grant": GRANT,
            "action": "result",
        },
        headers=participant_headers(),
    )
    assert access.status_code == 201
    assert access.get_json()["result"]["capability"] == CAPABILITY

    consumed = http.post(
        "/api/v1/internal/personal-insights/capabilities/consume",
        json={
            "analysisId": ANALYSIS_ID,
            "capability": CAPABILITY,
            "runId": RUN,
            "action": "result",
        },
        headers=node_headers(),
    )
    assert consumed.status_code == 200
    assert [call[0] for call in service.calls] == [
        "complete",
        "revalidate",
        "history_revalidate",
        "access",
        "consume",
    ]


def test_history_routes_expose_only_locator_metadata_and_one_use_access(client):
    http, service = client
    listed = http.get(
        "/api/v1/participant-auth/personal-insights/history?limit=10",
        headers=participant_headers(),
    )
    assert listed.status_code == 200
    assert set(listed.get_json()["result"][0]) == {
        "historyId",
        "analysisId",
        "algorithmVersion",
        "algorithmImageDigest",
        "status",
        "createdAt",
        "completedAt",
        "expiresAt",
        "correctionState",
        "updateAvailable",
    }
    assert GRANT not in listed.get_data(as_text=True)
    assert RUN not in listed.get_data(as_text=True)
    assert JOB not in listed.get_data(as_text=True)

    access = http.post(
        "/api/v1/participant-auth/personal-insights/history/{}/access".format(
            HISTORY
        ),
        json={"action": "result"},
        headers=participant_headers(),
    )
    assert access.status_code == 201
    assert set(access.get_json()["result"]) == {
        "capability",
        "historyId",
        "action",
        "expiresAt",
    }
    consumed = http.post(
        "/api/v1/internal/personal-insights/history/capabilities/consume",
        json={
            "analysisId": ANALYSIS_ID,
            "capability": CAPABILITY,
            "historyId": HISTORY,
            "action": "result",
        },
        headers=node_headers(),
    )
    assert consumed.status_code == 200
    assert [call[0] for call in service.calls] == [
        "history",
        "history_access",
        "history_consume",
    ]

    assert (
        http.get(
            "/api/v1/participant-auth/personal-insights/history?limit=0",
            headers=participant_headers(),
        ).status_code
        == 400
    )
    assert (
        http.post(
            "/api/v1/internal/personal-insights/history/capabilities/consume",
            json={
                "analysisId": ANALYSIS_ID,
                "capability": CAPABILITY,
                "historyId": HISTORY,
                "action": "result",
            },
        ).status_code
        == 401
    )


def test_internal_body_and_secret_headers_do_not_leak(client, monkeypatch):
    http, _service = client
    response = http.post(
        "/api/v1/internal/personal-insights/grants/claim",
        json={
            "analysisId": ANALYSIS_ID,
            "grant": GRANT,
            "jobId": JOB,
            "image": "caller-selected",
        },
        headers=node_headers(),
    )
    assert response.status_code == 400
    assert GRANT not in response.get_data(as_text=True)
    assert NODE_TOKEN not in response.get_data(as_text=True)

    def rejected(_analysis=ANALYSIS_ID):
        raise PersonalInsightError("private-record-id", 422)

    monkeypatch.setattr(route_module, "_personal_service", rejected)
    response = http.post(
        "/api/v1/participant-auth/personal-insights/resting-heart-overview/challenges",
        json={},
        headers=participant_headers(),
    )
    assert response.status_code == 422
    assert "private-record-id" not in response.get_data(as_text=True)
