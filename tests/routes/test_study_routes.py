from flask import Flask
import pytest

from routes import participant_auth_routes as route_module


ORIGIN = "http://127.0.0.1:3000"


class FakeStudyService:
    def __init__(self):
        self.calls = []

    def status(self, token, origin):
        self.calls.append(("status", token, origin))
        return {
            "schema": "brainstem.study-participant-status/v1",
            "studyId": "brainstem.real-world-recording-feasibility-repeatability",
        }

    def submit_survey(self, token, origin, body):
        self.calls.append(("survey", token, origin, body))
        return {"state": "active", "revision": 1}

    def challenge(self, token, origin, action, survey_body=None):
        self.calls.append(("challenge", token, origin, action, survey_body))
        return {
            "challengeId": "1" * 32,
            "message": "fixed",
            "expiresAt": 1785595500,
            "chainId": 11155420,
            "method": "personal_sign",
        }

    def apply(self, token, origin, challenge_id, signature, survey_body=None):
        self.calls.append(
            ("action", token, origin, challenge_id, signature, survey_body)
        )
        return {"status": "active", "enrollmentRevision": 1}


@pytest.fixture
def client(monkeypatch):
    service = FakeStudyService()
    monkeypatch.setattr(route_module, "_study_service", lambda *_args: service)
    application = Flask(__name__)
    application.register_blueprint(route_module.participant_auth_routes)
    return application.test_client(), service


def headers():
    return {
        "Authorization": "Participant participant-session",
        "X-Brainstem-Origin": ORIGIN,
    }


def test_fixed_study_status_and_signed_survey_action_are_narrow(client):
    http, service = client
    status = http.get(
        "/api/v1/participant-auth/studies/recording-feasibility/status",
        headers=headers(),
    )
    survey = http.post(
        "/api/v1/participant-auth/studies/recording-feasibility/challenges",
        json={"action": "survey", "surveyVersion": "1.0.0", "answers": {}},
        headers=headers(),
    )
    action = http.post(
        "/api/v1/participant-auth/studies/recording-feasibility/actions",
        json={
            "challengeId": "1" * 32,
            "signature": "0x" + "1" * 130,
            "surveyVersion": "1.0.0",
            "answers": {},
        },
        headers=headers(),
    )

    assert [value.status_code for value in (status, survey, action)] == [
        200,
        201,
        201,
    ]
    assert all(
        value.headers["Cache-Control"] == "private, no-store"
        for value in (status, survey, action)
    )
    assert [call[0] for call in service.calls] == [
        "status",
        "challenge",
        "action",
    ]


def test_read_session_cannot_write_survey_without_signature(client):
    http, service = client
    response = http.post(
        "/api/v1/participant-auth/studies/recording-feasibility/survey",
        json={"surveyVersion": "1.0.0", "answers": {}},
        headers=headers(),
    )
    assert response.status_code == 409
    assert service.calls == []


def test_researcher_status_is_only_a_safe_aggregate(client):
    http, service = client
    service.researcher_status = lambda: {
        "studyId": "brainstem.real-world-recording-feasibility-repeatability",
        "recruitment": "fewer_than_20",
        "participantAnswersExposed": False,
    }
    response = http.get(
        "/api/v1/studies/recording-feasibility/status",
        headers={"X-Brainstem-Origin": ORIGIN},
    )
    assert response.status_code == 200
    assert response.get_json()["result"]["participantAnswersExposed"] is False


def test_public_researcher_status_does_not_require_participant_auth(monkeypatch):
    from configparser import ConfigParser

    settings = ConfigParser()
    settings.read_dict({"brainstem_studies": {"enabled": "true"}})
    monkeypatch.setattr(route_module, "config", settings)
    monkeypatch.setattr(
        route_module,
        "_service",
        lambda: pytest.fail("participant auth must not be constructed"),
    )

    assert route_module._study_service(False).auth is None


def test_callers_cannot_add_a_study_or_protocol(client):
    http, _service = client
    response = http.post(
        "/api/v1/participant-auth/studies/recording-feasibility/challenges",
        json={"action": "enroll", "studyId": "caller-selected"},
        headers=headers(),
    )
    assert response.status_code == 400
