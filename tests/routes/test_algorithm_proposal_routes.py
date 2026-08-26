import ast
import json
from pathlib import Path

import pytest
from flask import Flask
from flask_jwt_extended import JWTManager, create_access_token

from commands.dataunions.brainstem.algorithm_proposals import (
    AlgorithmProposalWorkflow,
    ProposalNotFoundError,
)
from routes import algorithm_proposal_routes as route_module
from tests.algorithm_proposal_helpers import (
    ADMIN,
    OTHER,
    SCIENTIST,
    InMemoryProposalDao,
    revision_payload,
)


ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def client(monkeypatch):
    counter = iter(range(1000))
    dao = InMemoryProposalDao()
    workflow = AlgorithmProposalWorkflow(
        dao,
        clock=lambda: "2026-07-22T00:00:00Z",
        id_factory=lambda prefix: "{}_{}".format(prefix, next(counter)),
    )
    original_get = dao.get

    def get_or_not_found(proposal_id):
        try:
            return original_get(proposal_id)
        except KeyError:
            raise ProposalNotFoundError("Proposal not found")

    dao.get = get_or_not_found
    monkeypatch.setattr(route_module, "algorithm_proposal_workflow", workflow)

    application = Flask(__name__)
    application.config.update(
        JWT_SECRET_KEY="test-only-secret",
        JWT_TOKEN_LOCATION=["headers"],
        TESTING=True,
    )
    JWTManager(application)
    application.register_blueprint(route_module.algorithm_proposal_routes)
    with application.app_context():
        tokens = {
            "scientist": create_access_token(
                identity=SCIENTIST, additional_claims={"roles": ["user"]}
            ),
            "other": create_access_token(
                identity=OTHER, additional_claims={"roles": ["user"]}
            ),
            "admin": create_access_token(
                identity=ADMIN, additional_claims={"roles": ["admin"]}
            ),
            "string_admin": create_access_token(
                identity=ADMIN, additional_claims={"roles": "admin"}
            ),
        }
    return application.test_client(), tokens


def auth(token):
    return {"Authorization": "Bearer {}".format(token)}


def create_proposal(client, token, payload=None):
    return client.post(
        "/api/v1/algorithm-proposals",
        json=payload or revision_payload(),
        headers=auth(token),
    )


def test_authentication_ownership_and_admin_queue(client):
    http, tokens = client
    assert (
        http.post("/api/v1/algorithm-proposals", json=revision_payload()).status_code
        == 401
    )

    created = create_proposal(http, tokens["scientist"])
    assert created.status_code == 201
    proposal = created.get_json()["result"]

    own = http.get("/api/v1/algorithm-proposals", headers=auth(tokens["scientist"]))
    assert own.status_code == 200
    assert own.get_json()["result"]["rows"][0]["proposal_id"] == proposal["proposal_id"]

    denied = http.get(
        "/api/v1/algorithm-proposals/{}".format(proposal["proposal_id"]),
        headers=auth(tokens["other"]),
    )
    assert denied.status_code == 403

    queue_denied = http.get(
        "/api/v1/admin/algorithm-proposals", headers=auth(tokens["scientist"])
    )
    assert queue_denied.status_code == 403
    malformed_role_denied = http.get(
        "/api/v1/admin/algorithm-proposals", headers=auth(tokens["string_admin"])
    )
    assert malformed_role_denied.status_code == 403
    queue = http.get("/api/v1/admin/algorithm-proposals", headers=auth(tokens["admin"]))
    assert queue.status_code == 200
    assert queue.get_json()["result"]["rows"][0]["status"] == "submitted"


def test_admin_transitions_and_revision_conflicts(client):
    http, tokens = client
    proposal = create_proposal(http, tokens["scientist"]).get_json()["result"]
    event_url = "/api/v1/admin/algorithm-proposals/{}/events".format(
        proposal["proposal_id"]
    )
    reviewing = http.post(
        event_url,
        json={
            "type": "reviewing",
            "expected_revision_id": proposal["current_revision_id"],
        },
        headers=auth(tokens["admin"]),
    )
    assert reviewing.status_code == 200
    changes = http.post(
        event_url,
        json={
            "type": "changes_requested",
            "expected_revision_id": proposal["current_revision_id"],
            "note": "Add adversarial disclosure tests.",
        },
        headers=auth(tokens["admin"]),
    )
    assert changes.status_code == 200

    revised_payload = revision_payload(title="Resting R-R cohort summary v2")
    revised_payload["expected_revision_id"] = proposal["current_revision_id"]
    revision_url = "/api/v1/algorithm-proposals/{}/revisions".format(
        proposal["proposal_id"]
    )
    revised = http.post(
        revision_url, json=revised_payload, headers=auth(tokens["scientist"])
    )
    assert revised.status_code == 201
    assert revised.get_json()["result"]["current_revision_number"] == 2

    stale = http.post(
        event_url,
        json={
            "type": "reviewing",
            "expected_revision_id": proposal["current_revision_id"],
        },
        headers=auth(tokens["admin"]),
    )
    assert stale.status_code == 409


def test_pagination_validation_and_request_limits(client):
    http, tokens = client
    for index in range(3):
        response = create_proposal(
            http,
            tokens["scientist"],
            revision_payload(title="Algorithm {}".format(index)),
        )
        assert response.status_code == 201

    page = http.get(
        "/api/v1/algorithm-proposals?page=0&per_page=2",
        headers=auth(tokens["scientist"]),
    ).get_json()["result"]
    assert len(page["rows"]) == 2
    assert page["has_more"] is True
    invalid = http.get(
        "/api/v1/algorithm-proposals?page=-1&per_page=200",
        headers=auth(tokens["scientist"]),
    )
    assert invalid.status_code == 400

    oversized = revision_payload(scientific_purpose="x" * (17 * 1024))
    response = http.post(
        "/api/v1/algorithm-proposals",
        data=json.dumps(oversized),
        content_type="application/json",
        headers=auth(tokens["scientist"]),
    )
    assert response.status_code == 413


def test_only_bounded_json_is_accepted(client):
    http, tokens = client
    multipart = http.post(
        "/api/v1/algorithm-proposals",
        data={"source": (b"print('run')", "algorithm.py")},
        headers=auth(tokens["scientist"]),
    )
    assert multipart.status_code == 400

    payload = revision_payload(participant_data=[{"heart_rate": 70}])
    response = create_proposal(http, tokens["scientist"], payload)
    assert response.status_code == 400

    malformed = http.post(
        "/api/v1/algorithm-proposals",
        data=b"{not-json}",
        content_type="application/json",
        headers=auth(tokens["scientist"]),
    )
    assert malformed.status_code == 400

    invalid_id = http.get(
        "/api/v1/algorithm-proposals/_design%3Aall-docs",
        headers=auth(tokens["scientist"]),
    )
    assert invalid_id.status_code == 400


def test_proposal_api_has_no_execution_or_fetch_capability():
    paths = [
        ROOT / "routes" / "algorithm_proposal_routes.py",
        ROOT / "commands" / "dataunions" / "brainstem" / "algorithm_proposals.py",
        ROOT / "dao" / "algorithm_proposal_dao.py",
    ]
    forbidden_imports = {
        "requests",
        "subprocess",
        "urllib.request",
        "docker",
        "web3",
        "oceanprotocol",
    }
    forbidden_names = {"eval", "exec", "compile", "open"}
    forbidden_attributes = {
        "system",
        "popen",
        "run",
        "call",
        "check_call",
        "check_output",
    }
    for path in paths:
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                assert not ({alias.name for alias in node.names} & forbidden_imports)
            if isinstance(node, ast.ImportFrom):
                assert node.module not in forbidden_imports
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name):
                    assert node.func.id not in forbidden_names
                if isinstance(node.func, ast.Attribute):
                    assert node.func.attr.lower() not in forbidden_attributes
