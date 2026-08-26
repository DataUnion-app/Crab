from flask import Flask
from flask_jwt_extended import JWTManager, create_access_token

from routes import rewards as route_module


WALLET = "0x" + "1" * 40


def client(monkeypatch, source="brainstem"):
    preview = {
        "schema": "brainstem.reward-claim-preview/v1",
        "wallet": WALLET,
        "claimable": True,
        "blocker": None,
        "amountRaw": "1000000000000000000",
        "amountTokens": "1",
        "eligibilityCount": 1,
        "eligibilityCommitmentSha256": "a" * 64,
        "broadcast": False,
    }
    monkeypatch.setattr(
        route_module,
        "preview_brainstem_claim",
        lambda address, _users, _rewards: preview | {"wallet": address},
    )
    application = Flask(__name__)
    application.config["JWT_SECRET_KEY"] = "test-secret-that-is-long-enough-for-hs256"
    JWTManager(application)
    application.register_blueprint(
        route_module.reward_routes, url_prefix="/api/v1/rewards"
    )
    with application.app_context():
        token = create_access_token(
            identity=WALLET, additional_claims={"source": source}
        )
    return application.test_client(), token


def test_authenticated_brainstem_preview_is_private_and_identifier_free(monkeypatch):
    http, token = client(monkeypatch)
    response = http.get(
        "/api/v1/rewards/claim-preview",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "private, no-store"
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.get_json() == {
        "schema": "brainstem.reward-claim-preview/v1",
        "claimable": True,
        "blocker": None,
        "amountRaw": "1000000000000000000",
        "amountTokens": "1",
        "eligibilityCount": 1,
        "eligibilityCommitmentSha256": "a" * 64,
        "broadcast": False,
    }


def test_preview_requires_wallet_authentication_and_brainstem_source(monkeypatch):
    http, token = client(monkeypatch, source="default")

    assert http.get("/api/v1/rewards/claim-preview").status_code == 401
    response = http.get(
        "/api/v1/rewards/claim-preview",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 400
