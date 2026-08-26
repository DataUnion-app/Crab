from types import SimpleNamespace

from flask import Flask

from routes import brainstem_c2d_routes as route_module


TOKEN = "node-service-token-that-is-long-enough"
SECRET = "pseudonym-secret-that-is-long-enough"
KEY_ID = "generated-v1"
JOB_ID = "a" * 64
RELEASE_ID = "b" * 64
ADMIN_TOKEN = "admin-token-that-is-long-enough-for-tests"
STATUS_TOKEN = "status-token-that-is-long-enough-for-tests"
ANALYSIS_ID = "brainstem.resting-rr-cohort-summary/v1"
STUDY_ANALYSIS_ID = "brainstem.full-night-rr-signal-compatibility/v1"
PROPOSAL_ID = "study_" + "d" * 32
REVISION_ID = "revision_" + "e" * 32
REVISION_SHA256 = "f" * 64
DATA_PERMIT_ID = "data_permit_" + "1" * 32


class FakeExporter:
    def __init__(self, **_kwargs):
        pass

    def execute(self, job_id, release_id):
        assert job_id == JOB_ID
        assert release_id == RELEASE_ID
        return SimpleNamespace(
            body=b'{"participants":[],"policy":"brainstem.resting-rr/v1","schema":"brainstem.private-rr-cohort/v1"}',
            checksum="c" * 64,
            pseudonym_key_id=KEY_ID,
            source_snapshot_sha256="d" * 64,
        )


def app(monkeypatch):
    monkeypatch.setenv("BRAINSTEM_STUDY_RELEASE_VERSION", "1.0.0")
    monkeypatch.setenv("BRAINSTEM_STUDY_RELEASE_SHA256", "b" * 64)
    values = {
        "export_bearer_token": TOKEN,
        "pseudonym_secret": SECRET,
        "pseudonym_key_id": KEY_ID,
        "consent_version": "brainstem-tos-2026-07",
        "release_admin_bearer_token": ADMIN_TOKEN,
        "refresh_status_bearer_token": STATUS_TOKEN,
    }
    monkeypatch.setattr(route_module, "_setting", values.get)
    monkeypatch.setattr(route_module, "BrainstemC2DExporter", FakeExporter)
    application = Flask(__name__)
    application.register_blueprint(route_module.brainstem_c2d_routes)
    return application.test_client()


def test_route_fails_closed_without_service_auth(monkeypatch):
    client = app(monkeypatch)
    response = client.get(
        "/api/v1/internal/c2d/rr-cohort",
        headers={"X-Ocean-Compute-Job-Id": JOB_ID},
    )
    assert response.status_code == 401


def test_route_returns_bounded_verifiable_response(monkeypatch):
    client = app(monkeypatch)
    response = client.get(
        "/api/v1/internal/c2d/rr-cohort",
        headers={
            "Authorization": f"Bearer {TOKEN}",
            "X-Ocean-Compute-Job-Id": JOB_ID,
            "X-Brainstem-Cohort-Release-Id": RELEASE_ID,
            "X-Brainstem-Analysis-Id": ANALYSIS_ID,
        },
    )
    assert response.status_code == 200
    assert response.headers["Content-Type"] == "application/json"
    assert response.headers["Content-Length"] == str(len(response.data))
    assert response.headers["X-Content-SHA256"] == "c" * 64
    assert response.headers["X-Brainstem-Pseudonym-Key-Id"] == KEY_ID
    assert "X-Brainstem-Source-Snapshot-SHA256" not in response.headers
    assert response.headers["Cache-Control"] == "private, no-store"
    assert response.headers["X-Content-Type-Options"] == "nosniff"


def test_route_rejects_public_job_projection(monkeypatch):
    client = app(monkeypatch)
    response = client.get(
        "/api/v1/internal/c2d/rr-cohort",
        headers={
            "Authorization": f"Bearer {TOKEN}",
            "X-Ocean-Compute-Job-Id": f"cluster-{JOB_ID}",
            "X-Brainstem-Cohort-Release-Id": RELEASE_ID,
            "X-Brainstem-Analysis-Id": ANALYSIS_ID,
        },
    )
    assert response.status_code == 400


def test_route_requires_server_supplied_release_header(monkeypatch):
    client = app(monkeypatch)
    response = client.get(
        "/api/v1/internal/c2d/rr-cohort",
        headers={
            "Authorization": f"Bearer {TOKEN}",
            "X-Ocean-Compute-Job-Id": JOB_ID,
            "X-Brainstem-Analysis-Id": ANALYSIS_ID,
        },
    )
    assert response.status_code == 400


def test_study_analysis_rejects_a_release_other_than_the_governed_cohort(
    monkeypatch,
):
    monkeypatch.setenv("BRAINSTEM_FULL_NIGHT_COMPATIBILITY_REAL_DATA_ENABLED", "true")
    monkeypatch.setenv("BRAINSTEM_STUDY_ELIGIBILITY_RELEASE_ID", RELEASE_ID)
    client = app(monkeypatch)
    response = client.get(
        "/api/v1/internal/c2d/rr-cohort",
        headers={
            "Authorization": f"Bearer {TOKEN}",
            "X-Ocean-Compute-Job-Id": JOB_ID,
            "X-Brainstem-Cohort-Release-Id": "c" * 64,
            "X-Brainstem-Analysis-Id": (
                "brainstem.full-night-rr-signal-compatibility/v1"
            ),
        },
    )
    assert response.status_code == 400


def test_study_compute_requires_and_consumes_the_separate_one_shot_permit(
    monkeypatch,
):
    monkeypatch.setenv("BRAINSTEM_FULL_NIGHT_COMPATIBILITY_REAL_DATA_ENABLED", "true")
    monkeypatch.setenv("BRAINSTEM_STUDY_ELIGIBILITY_RELEASE_ID", RELEASE_ID)
    monkeypatch.setattr(route_module.study_proposal_dao, "get", lambda _value: {})
    binding = {
        "proposalId": PROPOSAL_ID,
        "revisionId": REVISION_ID,
        "revisionSha256": REVISION_SHA256,
        "releaseVersion": "1.0.0",
        "releaseSha256": "b" * 64,
        "reviewDecisions": [],
    }
    monkeypatch.setattr(
        route_module, "reviewed_revision_binding", lambda *_args: binding
    )

    class StudyExporter(FakeExporter):
        def execute(self, job_id, release_id, study_binding=None):
            assert study_binding == binding
            artifact = super().execute(job_id, release_id)
            artifact.source_snapshot_sha256 = "d" * 64
            return artifact

    class Authorization:
        def execute(self, proposal_id, permit_id, action, execution_id, callback):
            assert (proposal_id, permit_id, action, execution_id) == (
                PROPOSAL_ID,
                DATA_PERMIT_ID,
                "compute",
                JOB_ID,
            )
            artifact = callback(
                {
                    "proposalId": PROPOSAL_ID,
                    "revisionId": REVISION_ID,
                    "revisionSha256": REVISION_SHA256,
                    "cohortReleaseId": RELEASE_ID,
                }
            )
            return artifact, {"receiptSha256": "9" * 64}

    monkeypatch.setattr(
        route_module, "_data_authorization_service", lambda: Authorization()
    )
    client = app(monkeypatch)
    monkeypatch.setattr(route_module, "BrainstemC2DExporter", StudyExporter)
    response = client.get(
        "/api/v1/internal/c2d/rr-cohort",
        headers={
            "Authorization": f"Bearer {TOKEN}",
            "X-Ocean-Compute-Job-Id": JOB_ID,
            "X-Brainstem-Cohort-Release-Id": RELEASE_ID,
            "X-Brainstem-Analysis-Id": STUDY_ANALYSIS_ID,
            "X-Brainstem-Study-Proposal-Id": PROPOSAL_ID,
            "X-Brainstem-Study-Revision-Id": REVISION_ID,
            "X-Brainstem-Study-Revision-SHA256": REVISION_SHA256,
            "X-Brainstem-Study-Data-Permit-Id": DATA_PERMIT_ID,
        },
    )
    assert response.status_code == 200
    assert response.headers[
        "X-Brainstem-Study-Authorization-Receipt-SHA256"
    ] == "9" * 64


def test_route_requires_a_named_server_supplied_analysis(monkeypatch):
    client = app(monkeypatch)
    response = client.get(
        "/api/v1/internal/c2d/rr-cohort",
        headers={
            "Authorization": f"Bearer {TOKEN}",
            "X-Ocean-Compute-Job-Id": JOB_ID,
            "X-Brainstem-Cohort-Release-Id": RELEASE_ID,
        },
    )
    assert response.status_code == 400


def test_operator_can_create_then_activate_without_roster_projection(monkeypatch):
    client = app(monkeypatch)

    class FakeReleaseService:
        def create(self, roster, expires_at):
            assert roster == ["internal-user-a"]
            assert expires_at == "2026-08-01T00:00:00Z"
            return {
                "release_id": RELEASE_ID,
                "status": "draft",
                "expires_at": expires_at,
                "roster_user_ids": roster,
            }

        def activate(self, release_id, approval_reference):
            assert release_id == RELEASE_ID
            assert approval_reference == "privacy-review:ticket-123"
            return {
                "release_id": RELEASE_ID,
                "status": "active",
                "expires_at": "2026-08-01T00:00:00Z",
                "roster_user_ids": ["internal-user-a"],
            }

        def refresh_status(self, release_id):
            assert release_id == RELEASE_ID
            return {
                "state": "current",
                "revision": RELEASE_ID,
                "evaluatedAt": "2026-07-23T00:00:00Z",
            }

        def evaluate_refresh(self, release_id):
            assert release_id == RELEASE_ID
            return {
                "state": "refresh_available",
                "revision": "c" * 64,
                "evaluatedAt": "2026-07-25T00:00:00Z",
            }

    monkeypatch.setattr(route_module, "_release_service", FakeReleaseService)
    unauthorized = client.post(
        "/api/v1/internal/c2d/cohort-releases",
        json={
            "rosterUserIds": ["internal-user-a"],
            "expiresAt": "2026-08-01T00:00:00Z",
        },
    )
    assert unauthorized.status_code == 401

    created = client.post(
        "/api/v1/internal/c2d/cohort-releases",
        headers={"Authorization": f"Bearer {ADMIN_TOKEN}"},
        json={
            "rosterUserIds": ["internal-user-a"],
            "expiresAt": "2026-08-01T00:00:00Z",
        },
    )
    assert created.status_code == 201
    assert created.json == {
        "releaseId": RELEASE_ID,
        "status": "draft",
        "expiresAt": "2026-08-01T00:00:00Z",
    }
    assert "internal-user-a" not in created.get_data(as_text=True)

    activated = client.post(
        f"/api/v1/internal/c2d/cohort-releases/{RELEASE_ID}/activate",
        headers={"Authorization": f"Bearer {ADMIN_TOKEN}"},
        json={"approvalReference": "privacy-review:ticket-123"},
    )
    assert activated.status_code == 200
    assert activated.json["status"] == "active"
    assert "internal-user-a" not in activated.get_data(as_text=True)

    denied = client.get(f"/api/v1/internal/c2d/cohort-releases/{RELEASE_ID}/refresh")
    assert denied.status_code == 401
    status = client.get(
        f"/api/v1/internal/c2d/cohort-releases/{RELEASE_ID}/refresh",
        headers={"Authorization": f"Bearer {STATUS_TOKEN}"},
    )
    assert status.json == {
        "state": "current",
        "revision": RELEASE_ID,
        "evaluatedAt": "2026-07-23T00:00:00Z",
    }
    assert status.headers["Cache-Control"] == "private, no-store"
    assert status.headers["X-Content-Type-Options"] == "nosniff"
    evaluated = client.post(
        f"/api/v1/internal/c2d/cohort-releases/{RELEASE_ID}/refresh/evaluate",
        headers={"Authorization": f"Bearer {ADMIN_TOKEN}"},
    )
    assert evaluated.json["state"] == "refresh_available"


def test_value_commit_route_is_private_and_projects_only_commitment(monkeypatch):
    client = app(monkeypatch)

    class FakeValueService:
        def commit(self, receipt, signature):
            assert receipt == {"generated": True}
            assert signature == "generated-signature"
            return {
                "schema": "brainstem.participant-value-commitment/v1",
                "participantCount": 20,
            }

    monkeypatch.setattr(route_module, "_value_service", FakeValueService)
    unauthorized = client.post(
        "/api/v1/internal/c2d/value-commit",
        json={"receipt": {"generated": True}, "signature": "generated-signature"},
    )
    assert unauthorized.status_code == 401

    committed = client.post(
        "/api/v1/internal/c2d/value-commit",
        headers={"Authorization": f"Bearer {TOKEN}"},
        json={"receipt": {"generated": True}, "signature": "generated-signature"},
    )
    assert committed.status_code == 200
    assert committed.json == {
        "commitment": {
            "schema": "brainstem.participant-value-commitment/v1",
            "participantCount": 20,
        }
    }


def test_value_commit_route_rejects_oversized_chunked_body(monkeypatch):
    client = app(monkeypatch)
    monkeypatch.setattr(route_module, "_value_service", lambda: None)

    response = client.post(
        "/api/v1/internal/c2d/value-commit",
        headers={
            "Authorization": f"Bearer {TOKEN}",
            "Content-Type": "application/json",
        },
        data=b" " * (16 * 1024 + 1),
    )

    assert response.status_code == 413
