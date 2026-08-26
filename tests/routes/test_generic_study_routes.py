from configparser import ConfigParser
from pathlib import Path

from flask import Flask
from flask_jwt_extended import JWTManager, create_access_token
import pytest

from commands.dataunions.brainstem.study_registry import (
    APDET_DIAGNOSIS_QUESTIONNAIRE_ID,
    COMMUNITY_QUESTIONNAIRE_ID,
    DEFAULT_STUDY_REGISTRY,
)
from commands.dataunions.brainstem.study_proposals import StudyProposalForbidden
from routes import generic_study_routes as route_module
from dao.study_proposal_dao import SUMMARY_FIELDS


ORIGIN = "http://127.0.0.1:3000"


class Service:
    def __init__(self):
        self.calls = []

    def inbox(self, token, origin):
        self.calls.append(("inbox", token, origin))
        return {"schema": "brainstem.study-inbox/v1", "offerings": []}

    def status(self, token, origin, offering_id):
        self.calls.append(("status", token, origin, offering_id))
        return {"schema": "brainstem.study-offering-status/v1"}

    def tasks(self, token, origin, offering_id):
        self.calls.append(("tasks", token, origin, offering_id))
        return {"schema": "brainstem.participant-study-tasks/v1", "tasks": []}

    def challenge(
        self,
        token,
        origin,
        offering_id,
        action,
        answer=None,
        release_sha256=None,
    ):
        self.calls.append(
            (
                "challenge",
                token,
                origin,
                offering_id,
                action,
                answer,
                release_sha256,
            )
        )
        return {
            "challengeId": "1" * 32,
            "message": "fixed",
            "expiresAt": 1785595500,
            "chainId": 11155420,
            "method": "personal_sign",
        }

    def apply(self, token, origin, offering_id, challenge_id, signature):
        self.calls.append(
            ("apply", token, origin, offering_id, challenge_id, signature)
        )
        return {"schema": "brainstem.study-offering-status/v1"}


class RecurringService:
    def __init__(self):
        self.calls = []
        self.error = None

    def _result(self, value):
        if self.error is not None:
            raise self.error
        return value

    def status(self, token, origin, offering_id):
        self.calls.append(("status", token, origin, offering_id))
        return self._result(
            {"schema": "brainstem.study-recurring-status/v1", "state": "active"}
        )

    def challenge(self, token, origin, offering_id, action, settings):
        self.calls.append(
            ("challenge", token, origin, offering_id, action, settings)
        )
        return self._result(
            {
                "challengeId": "1" * 32,
                "message": "fixed study recurring authority",
                "expiresAt": 1785595500,
                "chainId": 11155420,
                "method": "personal_sign",
            }
        )

    def apply(self, token, origin, offering_id, challenge_id, signature):
        self.calls.append(
            ("apply", token, origin, offering_id, challenge_id, signature)
        )
        return self._result(
            {"schema": "brainstem.study-recurring-status/v1", "state": "active"}
        )

    def list_outbox(self, token, origin, offering_id):
        self.calls.append(("outbox", token, origin, offering_id))
        return self._result(
            {
                "schema": "brainstem.study-recurring-outbox/v1",
                "notifications": [],
            }
        )

    def acknowledge(self, token, origin, offering_id, notification_id):
        self.calls.append(
            ("read", token, origin, offering_id, notification_id)
        )
        return self._result(
            {
                "notificationId": notification_id,
                "messageKey": "study_result_ready",
                "state": "read",
            }
        )

    def delete_notification(self, token, origin, offering_id, notification_id):
        self.calls.append(
            ("delete", token, origin, offering_id, notification_id)
        )
        return self._result(None)


@pytest.fixture
def client(monkeypatch):
    service = Service()
    monkeypatch.setattr(route_module, "_generic_service", lambda: service)
    application = Flask(__name__)
    application.register_blueprint(route_module.generic_study_routes)
    return application.test_client(), service


@pytest.fixture
def recurring_client(monkeypatch):
    service = RecurringService()
    monkeypatch.setattr(route_module, "_study_recurring_service", lambda: service)
    application = Flask(__name__)
    application.register_blueprint(route_module.generic_study_routes)
    return application.test_client(), service


def headers():
    return {
        "Authorization": "Participant participant-session",
        "X-Brainstem-Origin": ORIGIN,
    }


def test_participant_inbox_status_and_exact_signed_action_routes(client):
    http, service = client
    release = DEFAULT_STUDY_REGISTRY.release(COMMUNITY_QUESTIONNAIRE_ID)
    inbox = http.get("/api/v1/participant-auth/studies/inbox", headers=headers())
    status = http.get(
        "/api/v1/participant-auth/studies/{}/status".format(
            COMMUNITY_QUESTIONNAIRE_ID
        ),
        headers=headers(),
    )
    challenge = http.post(
        "/api/v1/participant-auth/studies/{}/challenges".format(
            COMMUNITY_QUESTIONNAIRE_ID
        ),
        json={
            "action": "answer",
            "releaseSha256": release["releaseSha256"],
            "surveyVersion": "1.0.0",
            "answers": {"health_priority": "sleep"},
        },
        headers=headers(),
    )
    action = http.post(
        "/api/v1/participant-auth/studies/{}/actions".format(
            COMMUNITY_QUESTIONNAIRE_ID
        ),
        json={"challengeId": "1" * 32, "signature": "0x" + "1" * 130},
        headers=headers(),
    )

    assert [item.status_code for item in (inbox, status, challenge, action)] == [
        200,
        200,
        201,
        201,
    ]
    assert [call[0] for call in service.calls] == [
        "inbox",
        "status",
        "challenge",
        "apply",
    ]
    assert all(
        item.headers["Cache-Control"] == "private, no-store"
        for item in (inbox, status, challenge, action)
    )


def test_apply_rejects_repeated_answers_and_challenge_rejects_unknown_fields(client):
    http, service = client
    apply = http.post(
        "/api/v1/participant-auth/studies/{}/actions".format(
            COMMUNITY_QUESTIONNAIRE_ID
        ),
        json={
            "challengeId": "1" * 32,
            "signature": "0x" + "1" * 130,
            "answers": {"health_priority": "sleep"},
        },
        headers=headers(),
    )
    challenge = http.post(
        "/api/v1/participant-auth/studies/{}/challenges".format(
            COMMUNITY_QUESTIONNAIRE_ID
        ),
        json={
            "action": "delete",
            "releaseSha256": DEFAULT_STUDY_REGISTRY.release(
                COMMUNITY_QUESTIONNAIRE_ID
            )["releaseSha256"],
            "selector": "all",
        },
        headers=headers(),
    )
    assert apply.status_code == 400
    assert challenge.status_code == 400
    assert service.calls == []


def test_participant_tasks_route_is_read_only_and_rejects_query_filters(client):
    http, service = client
    url = "/api/v1/participant-auth/studies/{}/tasks".format(
        "brainstem.real-world-recording-feasibility-repeatability"
    )
    result = http.get(url, headers=headers())
    filtered = http.get(url + "?day=2", headers=headers())
    assert result.status_code == 200
    assert result.get_json()["result"]["tasks"] == []
    assert filtered.status_code == 400
    assert service.calls == [
        (
            "tasks",
            "participant-session",
            ORIGIN,
            "brainstem.real-world-recording-feasibility-repeatability",
        )
    ]


def test_study_recurring_routes_use_participant_auth_exact_bodies_and_no_store(
    recurring_client,
):
    http, service = recurring_client
    base = "/api/v1/participant-auth/studies/{}/recurring".format(
        COMMUNITY_QUESTIONNAIRE_ID
    )
    notification_id = "n" * 64
    settings = {
        "minimumNewData": 3,
        "cadenceSeconds": 86400,
        "maxRunsPer30Days": 7,
        "expiresAt": 1785595500,
        "retentionDays": 30,
        "delivery": "in_app",
        "billing": "no_charge",
        "charge": 0,
    }

    responses = [
        http.get(base, headers=headers()),
        http.post(
            base + "/challenges",
            json={"action": "activate", "settings": settings},
            headers=headers(),
        ),
        http.post(
            base + "/actions",
            json={"challengeId": "1" * 32, "signature": "0x" + "1" * 130},
            headers=headers(),
        ),
        http.get(base + "/outbox", headers=headers()),
        http.post(
            base + "/outbox/{}/read".format(notification_id),
            json={},
            headers=headers(),
        ),
        http.delete(
            base + "/outbox/{}".format(notification_id), headers=headers()
        ),
    ]

    assert [response.status_code for response in responses] == [
        200,
        201,
        201,
        200,
        200,
        204,
    ]
    assert [call[0] for call in service.calls] == [
        "status",
        "challenge",
        "apply",
        "outbox",
        "read",
        "delete",
    ]
    assert service.calls[1][1:] == (
        "participant-session",
        ORIGIN,
        COMMUNITY_QUESTIONNAIRE_ID,
        "activate",
        settings,
    )
    assert all(
        response.headers["Cache-Control"] == "private, no-store"
        for response in responses
    )


def test_study_recurring_routes_reject_extra_fields_bodies_and_queries(
    recurring_client,
):
    http, service = recurring_client
    base = "/api/v1/participant-auth/studies/{}/recurring".format(
        COMMUNITY_QUESTIONNAIRE_ID
    )
    rejected = [
        http.get(base + "?include=private", headers=headers()),
        http.post(
            base + "/challenges",
            json={"action": "pause", "settings": {}},
            headers=headers(),
        ),
        http.post(
            base + "/actions",
            json={
                "challengeId": "1" * 32,
                "signature": "0x" + "1" * 130,
                "offeringId": COMMUNITY_QUESTIONNAIRE_ID,
            },
            headers=headers(),
        ),
        http.get(base + "/outbox?state=unread", headers=headers()),
        http.post(
            base + "/outbox/{}/read".format("n" * 64),
            json={"read": True},
            headers=headers(),
        ),
        http.delete(
            base + "/outbox/{}".format("n" * 64),
            json={},
            headers=headers(),
        ),
    ]
    assert all(response.status_code == 400 for response in rejected)
    assert service.calls == []


def test_study_recurring_errors_are_sanitized_and_no_worker_route_exists(
    recurring_client,
):
    http, service = recurring_client
    base = "/api/v1/participant-auth/studies/{}/recurring".format(
        COMMUNITY_QUESTIONNAIRE_ID
    )
    service.error = route_module.StudyRecurringError(
        "sensitive_internal_authority_failure", 503
    )
    failed = http.get(base, headers=headers())
    absent = http.post(base + "/worker", json={}, headers=headers())
    assert failed.status_code == 503
    assert failed.get_json() == {
        "status": "failed",
        "message": "Study recurring service unavailable",
    }
    assert "sensitive_internal_authority_failure" not in failed.get_data(as_text=True)
    assert failed.headers["Cache-Control"] == "private, no-store"
    assert absent.status_code == 404


def test_new_feature_is_default_off(monkeypatch):
    settings = ConfigParser()
    settings.read_dict({"brainstem_generic_studies": {"enabled": "false"}})
    monkeypatch.setattr(route_module, "config", settings)
    application = Flask(__name__)
    application.register_blueprint(route_module.generic_study_routes)
    response = application.test_client().get("/api/v1/studies/catalogue")
    assert response.status_code == 503


def test_study_preview_and_results_share_the_full_night_selector(monkeypatch):
    settings = ConfigParser()
    settings.read_dict(
        {
            "application": {"upload_folder": "data"},
            "brainstem_c2d": {"consent_version": "generated-consent-v1"},
        }
    )
    monkeypatch.setattr(route_module, "config", settings)
    monkeypatch.setenv("BRAINSTEM_STUDY_ELIGIBILITY_PREVIEW_ENABLED", "true")
    monkeypatch.setenv("BRAINSTEM_STUDY_RESULTS_ENABLED", "true")
    monkeypatch.setenv("BRAINSTEM_STUDY_RESULT_ALGORITHM_DIGEST", "sha256:" + "a" * 64)
    monkeypatch.setenv("BRAINSTEM_STUDY_ELIGIBILITY_RELEASE_ID", "b" * 64)
    monkeypatch.setenv("BRAINSTEM_STUDY_RELEASE_VERSION", "1.0.0")
    monkeypatch.setenv("BRAINSTEM_STUDY_RELEASE_SHA256", "c" * 64)

    preview = route_module._eligibility_preview_service()
    monkeypatch.setenv("BRAINSTEM_STUDY_ELIGIBILITY_PREVIEW_ENABLED", "false")
    results = route_module._study_result_service()

    assert preview.exporter.policy.analysis_id == (
        "brainstem.full-night-rr-signal-compatibility/v1"
    )
    assert results.selector.policy is preview.exporter.policy


def test_generated_blueprint_registration_is_feature_gated():
    source = (Path(__file__).resolve().parents[2] / "app.py").read_text()
    assert 'config.has_section("brainstem_generic_studies")' in source
    assert 'getboolean("enabled", fallback=False)' in source
    assert "app.register_blueprint(generic_study_routes)" in source


def test_feature_requires_both_enabled_and_generated_only(monkeypatch):
    settings = ConfigParser()
    settings.read_dict(
        {
            "brainstem_generic_studies": {
                "enabled": "true",
                "generated_only": "false",
            }
        }
    )
    monkeypatch.setattr(route_module, "config", settings)
    assert route_module._enabled() is False
    assert route_module._participant_enabled() is False
    settings["brainstem_generic_studies"]["generated_only"] = "true"
    assert route_module._enabled() is True
    assert route_module._participant_enabled() is False
    settings.read_dict({"brainstem_studies": {"enabled": "true"}})
    assert route_module._participant_enabled() is True
    assert route_module._operator_enabled() is False
    settings["brainstem_generic_studies"]["operator_operations_enabled"] = "true"
    assert route_module._operator_enabled() is True
    assert route_module._data_actions_enabled() is False
    monkeypatch.setenv("BRAINSTEM_STUDY_REAL_DATA_ACTIONS_ENABLED", "true")
    assert route_module._data_actions_enabled() is False
    settings["brainstem_generic_studies"]["generated_only"] = "false"
    assert route_module._data_actions_enabled() is True
    assert route_module._participant_enabled() is False
    monkeypatch.setenv("BRAINSTEM_STUDY_MEMBER_SURVEYS_ENABLED", "true")
    assert route_module._participant_enabled() is False
    monkeypatch.setenv(
        "BRAINSTEM_STUDY_MEMBER_SURVEY_RELEASE_SHA256",
        route_module.APDET_DIAGNOSIS_QUESTIONNAIRE_RELEASE_SHA256,
    )
    assert route_module._participant_enabled() is True
    monkeypatch.delenv("BRAINSTEM_STUDY_MEMBER_SURVEYS_ENABLED")
    monkeypatch.delenv("BRAINSTEM_STUDY_MEMBER_SURVEY_RELEASE_SHA256")
    monkeypatch.delenv("BRAINSTEM_STUDY_REAL_DATA_ACTIONS_ENABLED")
    assert route_module._data_actions_enabled() is False
    settings["brainstem_generic_studies"]["generated_only"] = "true"
    assert route_module._recurring_enabled() is False

    settings.read_dict(
        {
            "brainstem_recurring_insights": {
                "enabled": "true",
                "generated_worker_enabled": "false",
                "external_delivery_enabled": "false",
            }
        }
    )
    assert route_module._recurring_enabled() is True

    sample = ConfigParser()
    sample.read(Path(__file__).resolve().parents[2] / "sample.ini")
    assert sample["brainstem_generic_studies"].getboolean("enabled") is False
    assert (
        sample["brainstem_generic_studies"].getboolean("generated_only")
        is False
    )
    assert (
        sample["brainstem_generic_studies"].getboolean(
            "operator_operations_enabled"
        )
        is False
    )
    assert sample["brainstem_generic_studies"].get("operator_wallets") == ""
    assert sample["brainstem_generic_studies"].get(
        "participant_binding_secret"
    ).startswith("<")
    assert sample["brainstem_generic_studies"].get(
        "participant_binding_key_id"
    ) == "generated-study-binding-2026-01"
    assert sample["brainstem_recurring_insights"].getboolean("enabled") is False
    assert (
        sample["brainstem_recurring_insights"].getboolean(
            "generated_worker_enabled"
        )
        is False
    )
    assert (
        sample["brainstem_recurring_insights"].getboolean(
            "external_delivery_enabled"
        )
        is False
    )


def test_first_study_questionnaire_access_requires_current_cohort_membership(
    monkeypatch,
):
    settings = ConfigParser()
    settings.read_dict(
        {"brainstem_c2d": {"consent_version": "brainstem-research-v1"}}
    )
    monkeypatch.setattr(route_module, "config", settings)
    monkeypatch.setenv("BRAINSTEM_STUDY_ELIGIBILITY_RELEASE_ID", "a" * 64)

    class Releases:
        def __init__(self, _release_dao, _users_dao, consent_version, purpose):
            assert consent_version == "brainstem-research-v1"
            assert purpose == "brainstem.full-night-rr-signal-compatibility/v1"

        def active_member_ids(self, release_id):
            assert release_id == "a" * 64
            return {"participant-one"}

    monkeypatch.setattr(route_module, "CohortReleaseService", Releases)
    consenting = {
        "_id": "participant-one",
        "usage_flag": "ACCEPTED",
        "guidelines_acceptance_flag": "ACCEPTED",
    }
    assert route_module._participant_offering_access(
        APDET_DIAGNOSIS_QUESTIONNAIRE_ID, consenting
    )
    assert not route_module._participant_offering_access(
        APDET_DIAGNOSIS_QUESTIONNAIRE_ID,
        {**consenting, "_id": "participant-two"},
    )
    assert not route_module._participant_offering_access(
        APDET_DIAGNOSIS_QUESTIONNAIRE_ID,
        {**consenting, "usage_flag": "REJECTED"},
    )


class ProposalWorkflow:
    def __init__(self):
        self.calls = []
        self.status = "submitted"

    def create(self, actor, body):
        self.calls.append(("create", actor, body))
        return {"proposalId": "study_1", "status": "draft"}

    def list_queue(self, page, per_page, status):
        self.calls.append(("queue", page, per_page, status))
        return {"rows": [], "page": page, "perPage": per_page, "hasMore": False}

    def get(self, proposal_id, actor, can_review=False):
        self.calls.append(("get", proposal_id, actor, can_review))
        if not can_review and actor != "0x" + "1" * 40:
            raise StudyProposalForbidden("Study access denied")
        return {"proposalId": proposal_id, "status": self.status}

    def review(
        self,
        proposal_id,
        actor,
        domain,
        decision,
        revision,
        revision_sha256,
        note,
        evidence_sha256,
    ):
        self.calls.append(
            (
                "review",
                proposal_id,
                actor,
                domain,
                decision,
                revision,
                revision_sha256,
                note,
                evidence_sha256,
            )
        )
        return {"proposalId": proposal_id, "status": "reviewing"}


@pytest.fixture
def proposal_client(monkeypatch):
    workflow = ProposalWorkflow()
    monkeypatch.setattr(route_module, "study_proposal_workflow", workflow)
    monkeypatch.setattr(route_module, "_require_enabled", lambda: None)
    application = Flask(__name__)
    application.config.update(
        JWT_SECRET_KEY="test-only-key-that-is-long-enough-for-hs256",
        JWT_TOKEN_LOCATION=["headers"],
        TESTING=True,
    )
    JWTManager(application)
    application.register_blueprint(route_module.generic_study_routes)
    with application.app_context():
        tokens = {
            "author": create_access_token(
                identity="0x" + "1" * 40,
                additional_claims={"roles": ["user", "study_researcher"]},
            ),
            "participant": create_access_token(
                identity="0x" + "4" * 40,
                additional_claims={"roles": ["user"]},
            ),
            "science": create_access_token(
                identity="0x" + "2" * 40,
                additional_claims={"roles": ["study_reviewer_scientific"]},
            ),
            "ethics": create_access_token(
                identity="0x" + "3" * 40,
                additional_claims={"roles": ["study_reviewer_ethics"]},
            ),
        }
    return application.test_client(), tokens, workflow


def _auth(token):
    return {"Authorization": "Bearer {}".format(token)}


def _proposal_payload():
    release = DEFAULT_STUDY_REGISTRY.release(
        "brainstem.real-world-recording-feasibility-repeatability"
    )
    return {
        "title": "Generated study proposal",
        "purpose": "A sufficiently bounded generated scientific purpose.",
        "population": "Adults in a generated local fixture only.",
        "participantBurden": "One generated action each day.",
        "recordings": "Generated recordings only.",
        "surveyOutline": "A bounded generated questionnaire.",
        "schedule": "Fourteen days.",
        "endpoints": "Generated aggregate endpoints.",
        "analysisPlan": "A bounded generated aggregate analysis plan.",
        "retention": "Generated evidence is retained for thirty days.",
        "resultReturnPlan": "Return a generated aggregate summary.",
        "sourcePapers": ["https://doi.org/10.1000/generated"],
        "conflicts": "No generated conflicts.",
        "offeringId": release["offeringId"],
        "releaseVersion": release["releaseVersion"],
        "releaseSha256": release["releaseSha256"],
    }


def test_proposal_routes_enforce_authorship_and_domain_reviewer_roles(proposal_client):
    http, tokens, workflow = proposal_client
    assert http.post("/api/v1/study-proposals", json=_proposal_payload()).status_code == 401
    assert http.post(
        "/api/v1/study-proposals",
        json=_proposal_payload(),
        headers=_auth(tokens["participant"]),
    ).status_code == 403
    assert http.post(
        "/api/v1/study-proposals",
        json=_proposal_payload(),
        headers=_auth(tokens["author"]),
    ).status_code == 201
    assert http.get(
        "/api/v1/admin/study-proposals", headers=_auth(tokens["author"])
    ).status_code == 403
    assert http.get(
        "/api/v1/admin/study-proposals", headers=_auth(tokens["science"])
    ).status_code == 200
    assert http.get(
        "/api/v1/admin/study-proposals/study_1", headers=_auth(tokens["author"])
    ).status_code == 403
    assert http.get(
        "/api/v1/admin/study-proposals/study_1", headers=_auth(tokens["science"])
    ).status_code == 200
    assert http.get(
        "/api/v1/study-proposals/study_1", headers=_auth(tokens["science"])
    ).status_code == 403

    workflow.status = "draft"
    assert http.get(
        "/api/v1/admin/study-proposals/study_1", headers=_auth(tokens["science"])
    ).status_code == 404
    for status in ("changes_requested", "review_complete"):
        workflow.status = status
        assert http.get(
            "/api/v1/admin/study-proposals/study_1",
            headers=_auth(tokens["science"]),
        ).status_code == 200
    workflow.status = "submitted"

    review_url = "/api/v1/admin/study-proposals/study_1/reviews"
    review_body = {
        "domain": "scientific",
        "decision": "approved",
        "expectedRevisionId": "revision_1",
        "expectedRevisionSha256": "a" * 64,
        "note": "This exact generated revision meets the scientific checkpoint.",
        "evidenceSha256": "b" * 64,
    }
    assert http.post(
        review_url, json=review_body, headers=_auth(tokens["ethics"])
    ).status_code == 403
    assert http.post(
        review_url, json=review_body, headers=_auth(tokens["science"])
    ).status_code == 201
    assert [call[0] for call in workflow.calls] == [
        "create",
        "queue",
        "get",
        "get",
        "get",
        "get",
        "get",
        "review",
    ]


def test_no_activation_route_exists(proposal_client):
    http, tokens, _workflow = proposal_client
    response = http.post(
        "/api/v1/admin/study-proposals/study_1/activate",
        json={},
        headers=_auth(tokens["science"]),
    )
    assert response.status_code == 404


class ActivationService:
    def __init__(self):
        self.calls = []

    def create_challenge(
        self,
        proposal_id,
        operator,
        origin,
        revision_id,
        revision_sha256,
    ):
        self.calls.append(
            (
                "challenge",
                proposal_id,
                operator,
                origin,
                revision_id,
                revision_sha256,
            )
        )
        return {
            "challengeId": "1" * 32,
            "message": "inspect exact generated bundle",
            "bundle": {"bundleSha256": "b" * 64},
        }

    def apply(self, proposal_id, operator, origin, challenge_id, signature):
        self.calls.append(
            ("permit", proposal_id, operator, origin, challenge_id, signature)
        )
        return {"permitId": "permit_" + "2" * 32, "status": "permitted"}


class OperationsService:
    def __init__(self):
        self.calls = []

    def status(self, proposal_id, permit_id):
        self.calls.append(("status", proposal_id, permit_id))
        return {
            "schema": "brainstem.study-operations-status/v1",
            "state": {"lifecycleState": "permitted", "stateSha256": "a" * 64},
            "events": [],
        }

    def create_challenge(
        self,
        proposal_id,
        operator,
        origin,
        permit_id,
        action,
        expected_state_sha256,
        idempotency_key,
        details,
    ):
        self.calls.append(
            (
                "challenge",
                proposal_id,
                operator,
                origin,
                permit_id,
                action,
                expected_state_sha256,
                idempotency_key,
                details,
            )
        )
        return {
            "challengeId": "3" * 32,
            "message": "inspect exact operation bundle",
            "bundle": {"bundleSha256": "b" * 64},
        }

    def apply(self, proposal_id, operator, origin, challenge_id, signature):
        self.calls.append(
            (
                "transition",
                proposal_id,
                operator,
                origin,
                challenge_id,
                signature,
            )
        )
        return {
            "schema": "brainstem.study-operation-result/v1",
            "state": {"lifecycleState": "recruiting"},
        }

    def researcher_projection(self, proposal_id, permit_id, metrics_source):
        self.calls.append(
            ("researcher", proposal_id, permit_id, metrics_source)
        )
        return {
            "schema": "brainstem.researcher-study-operations/v1",
            "bands": {"recruitment": "under_disclosure_floor"},
        }


@pytest.fixture
def activation_client(monkeypatch):
    service = ActivationService()
    monkeypatch.setattr(route_module, "_require_operator_enabled", lambda: None)
    monkeypatch.setattr(route_module, "_activation_service", lambda: service)
    application = Flask(__name__)
    application.config.update(
        JWT_SECRET_KEY="test-only-key-that-is-long-enough-for-hs256",
        JWT_TOKEN_LOCATION=["headers"],
        TESTING=True,
    )
    JWTManager(application)
    application.register_blueprint(route_module.generic_study_routes)
    with application.app_context():
        tokens = {
            "operator": create_access_token(
                identity="0x" + "4" * 40,
                additional_claims={"roles": ["study_operator"]},
            ),
            "admin": create_access_token(
                identity="0x" + "5" * 40,
                additional_claims={"roles": ["admin"]},
            ),
        }
    return application.test_client(), tokens, service


@pytest.fixture
def operations_client(monkeypatch):
    service = OperationsService()
    monkeypatch.setattr(route_module, "_require_operator_enabled", lambda: None)
    monkeypatch.setattr(route_module, "_operations_service", lambda: service)
    application = Flask(__name__)
    application.config.update(
        JWT_SECRET_KEY="test-only-key-that-is-long-enough-for-hs256",
        JWT_TOKEN_LOCATION=["headers"],
        TESTING=True,
    )
    JWTManager(application)
    application.register_blueprint(route_module.generic_study_routes)
    with application.app_context():
        tokens = {
            "operator": create_access_token(
                identity="0x" + "4" * 40,
                additional_claims={"roles": ["study_operator"]},
            ),
            "admin": create_access_token(
                identity="0x" + "5" * 40,
                additional_claims={"roles": ["admin"]},
            ),
            "researcher": create_access_token(
                identity="0x" + "6" * 40,
                additional_claims={"roles": ["study_researcher"]},
            ),
        }
    return application.test_client(), tokens, service


def test_operator_routes_accept_only_exact_revision_and_signature_bodies(
    activation_client,
):
    http, tokens, service = activation_client
    url = "/api/v1/admin/study-proposals/study_1/activation"
    request_headers = {
        **_auth(tokens["operator"]),
        "Origin": ORIGIN,
        "X-Brainstem-Origin": ORIGIN,
    }
    challenge = http.post(
        url + "/challenges",
        json={
            "expectedRevisionId": "revision_1",
            "expectedRevisionSha256": "a" * 64,
        },
        headers=request_headers,
    )
    permit = http.post(
        url + "/permits",
        json={"challengeId": "1" * 32, "signature": "0x" + "3" * 130},
        headers=request_headers,
    )

    assert challenge.status_code == 201
    assert permit.status_code == 201
    assert permit.get_json()["result"]["status"] == "permitted"
    assert [item[0] for item in service.calls] == ["challenge", "permit"]
    assert all(
        response.headers["Cache-Control"] == "private, no-store"
        for response in (challenge, permit)
    )

    assert http.post(
        url + "/challenges",
        json={
            "expectedRevisionId": "revision_1",
            "expectedRevisionSha256": "a" * 64,
            "releaseSha256": "b" * 64,
        },
        headers=request_headers,
    ).status_code == 400
    assert http.post(
        url + "/permits",
        json={
            "challengeId": "1" * 32,
            "signature": "0x" + "3" * 130,
            "activate": True,
        },
        headers=request_headers,
    ).status_code == 400
    assert len(service.calls) == 2


def test_admin_cannot_substitute_for_study_operator(activation_client):
    http, tokens, service = activation_client
    response = http.post(
        "/api/v1/admin/study-proposals/study_1/activation/challenges",
        json={
            "expectedRevisionId": "revision_1",
            "expectedRevisionSha256": "a" * 64,
        },
        headers={
            **_auth(tokens["admin"]),
            "Origin": ORIGIN,
            "X-Brainstem-Origin": ORIGIN,
        },
    )
    assert response.status_code == 403
    assert service.calls == []


def test_permit_does_not_create_recruitment_materialization_or_participant_routes(
    activation_client,
):
    http, tokens, service = activation_client
    request_headers = {
        **_auth(tokens["operator"]),
        "Origin": ORIGIN,
        "X-Brainstem-Origin": ORIGIN,
    }
    for suffix in ("recruit", "activate", "materialize", "participants"):
        response = http.post(
            "/api/v1/admin/study-proposals/study_1/{}".format(suffix),
            json={},
            headers=request_headers,
        )
        assert response.status_code == 404
    assert service.calls == []


def test_operator_routes_reject_missing_or_spoofed_actual_origin(activation_client):
    http, tokens, service = activation_client
    url = "/api/v1/admin/study-proposals/study_1/activation/challenges"
    body = {
        "expectedRevisionId": "revision_1",
        "expectedRevisionSha256": "a" * 64,
    }
    authorization = _auth(tokens["operator"])

    missing = http.post(
        url,
        json=body,
        headers={**authorization, "X-Brainstem-Origin": ORIGIN},
    )
    mismatch = http.post(
        url,
        json=body,
        headers={
            **authorization,
            "Origin": ORIGIN,
            "X-Brainstem-Origin": "https://spoofed.example",
        },
    )
    actual_only = http.post(
        url,
        json=body,
        headers={**authorization, "Origin": ORIGIN},
    )

    assert missing.status_code == 403
    assert mismatch.status_code == 403
    assert actual_only.status_code == 201
    assert len(service.calls) == 1
    assert service.calls[0][3] == ORIGIN


def test_operation_routes_are_strict_operator_only_and_bind_actual_origin(
    operations_client,
):
    http, tokens, service = operations_client
    base = "/api/v1/admin/study-proposals/study_1/operations"
    headers = {
        **_auth(tokens["operator"]),
        "Origin": ORIGIN,
        "X-Brainstem-Origin": ORIGIN,
    }
    status = http.get(
        base + "?permitId=permit_" + "2" * 32,
        headers=headers,
    )
    challenge = http.post(
        base + "/challenges",
        json={
            "permitId": "permit_" + "2" * 32,
            "action": "recruit",
            "expectedStateSha256": "a" * 64,
            "idempotencyKey": "generated-operation-route",
            "details": {},
        },
        headers=headers,
    )
    transition = http.post(
        base + "/transitions",
        json={"challengeId": "3" * 32, "signature": "0x" + "4" * 130},
        headers=headers,
    )
    assert [item.status_code for item in (status, challenge, transition)] == [
        200,
        201,
        201,
    ]
    assert [call[0] for call in service.calls] == [
        "status",
        "challenge",
        "transition",
    ]
    assert service.calls[1][3] == ORIGIN
    assert all(
        response.headers["Cache-Control"] == "private, no-store"
        for response in (status, challenge, transition)
    )

    unknown = http.post(
        base + "/challenges",
        json={
            "permitId": "permit_" + "2" * 32,
            "action": "recruit",
            "expectedStateSha256": "a" * 64,
            "idempotencyKey": "generated-operation-extra",
            "details": {},
            "participantIds": [],
        },
        headers=headers,
    )
    admin = http.post(
        base + "/challenges",
        json={
            "permitId": "permit_" + "2" * 32,
            "action": "recruit",
            "expectedStateSha256": "a" * 64,
            "idempotencyKey": "generated-operation-admin",
            "details": {},
        },
        headers={
            **_auth(tokens["admin"]),
            "Origin": ORIGIN,
            "X-Brainstem-Origin": ORIGIN,
        },
    )
    assert unknown.status_code == 400
    assert admin.status_code == 403
    assert len(service.calls) == 3


def test_researcher_projection_is_researcher_only_and_has_no_metric_filters(
    operations_client,
):
    http, tokens, service = operations_client
    base = "/api/v1/researcher/study-proposals/study_1/operations"
    permit = "permit_" + "2" * 32
    result = http.get(
        base + "?permitId=" + permit,
        headers=_auth(tokens["researcher"]),
    )
    admin = http.get(
        base + "?permitId=" + permit,
        headers=_auth(tokens["admin"]),
    )
    filtered = http.get(
        base + "?permitId={}&cohort=small".format(permit),
        headers=_auth(tokens["researcher"]),
    )
    assert result.status_code == 200
    assert result.get_json()["result"]["bands"] == {
        "recruitment": "under_disclosure_floor"
    }
    assert admin.status_code == 403
    assert filtered.status_code == 400
    assert len(service.calls) == 1
    assert service.calls[0][:3] == ("researcher", "study_1", permit)


def test_study_result_receipts_have_a_separate_bounded_request_envelope():
    application = Flask(__name__)
    payload = {"result": {"summary": "x" * (33 * 1024)}}
    with application.test_request_context(
        "/api/v1/internal/study-proposals/study_1/results",
        method="POST",
        json=payload,
    ):
        assert route_module._json_body(
            route_module.MAX_STUDY_RESULT_BODY_BYTES
        ) == payload


def test_proposal_list_storage_projection_contains_full_bounded_documents():
    assert set(SUMMARY_FIELDS) == {
        "type",
        "schema",
        "proposalId",
        "authorId",
        "title",
        "status",
        "currentRevisionId",
        "currentRevisionNumber",
        "currentRevisionSha256",
        "createdAt",
        "updatedAt",
        "access",
        "revisions",
        "reviews",
        "events",
    }
