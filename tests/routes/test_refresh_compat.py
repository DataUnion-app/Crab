import time
from datetime import datetime, timedelta, timezone

import jwt
from flask import Flask
from flask_jwt_extended import JWTManager, create_refresh_token, decode_token

from routes import authentication_routes as route_module


def test_current_and_unexpired_legacy_refresh_tokens(monkeypatch):
    current_secret = "current-test-secret-that-has-at-least-32-bytes"
    legacy_secret = "legacy-test-secret-that-also-has-at-least-32-bytes"
    wallet = route_module.Web3.to_checksum_address(
        "0x1111111111111111111111111111111111111111"
    )

    application = Flask(__name__)
    application.config["JWT_SECRET_KEY"] = current_secret
    jwt_manager = JWTManager(application)

    @jwt_manager.token_in_blocklist_loader
    def is_revoked(_header, payload):
        return payload["jti"] == "revoked-current-jti"

    application.register_blueprint(route_module.authentication_routes)

    monkeypatch.setitem(
        route_module.config["application"],
        "legacy_jwt_refresh_secret_string",
        legacy_secret,
    )
    monkeypatch.setitem(
        route_module.config["application"],
        "legacy_jwt_refresh_deadline_epoch",
        str(int(time.time()) + 3600),
    )
    revoked_jtis = set()
    monkeypatch.setattr(
        route_module.sessions_dao,
        "is_blacklisted",
        lambda jti: jti in revoked_jtis,
    )
    monkeypatch.setattr(
        route_module.sessions_dao,
        "add_to_blacklist",
        revoked_jtis.add,
    )
    monkeypatch.setattr(
        route_module.user_dao,
        "get_by_public_address",
        lambda public_address: {
            "result": [{"_id": "user-id", "claims": [], "is_access_blocked": False}]
        },
    )

    now = datetime.now(timezone.utc)
    legacy_token = jwt.encode(
        {
            "sub": wallet,
            "type": "refresh",
            "source": "brainstem",
            "roles": [],
            "jti": "legacy-refresh-jti",
            "iat": now,
            "nbf": now,
            "exp": now + timedelta(minutes=5),
        },
        legacy_secret,
        algorithm="HS256",
    )
    with application.app_context():
        current_token = create_refresh_token(
            identity=wallet,
            additional_claims={"source": "brainstem", "roles": []},
        )
        revoked_current_token = create_refresh_token(
            identity=wallet,
            additional_claims={
                "source": "brainstem",
                "roles": [],
                "jti": "revoked-current-jti",
            },
        )

    client = application.test_client()
    for token in (current_token, legacy_token):
        response = client.post(
            "/refresh", headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 200
        with application.app_context():
            assert decode_token(response.get_json()["access_token"])["sub"] == wallet

    expired = jwt.encode(
        {
            "sub": wallet,
            "type": "refresh",
            "source": "brainstem",
            "jti": "expired-legacy-refresh-jti",
            "iat": now - timedelta(minutes=10),
            "nbf": now - timedelta(minutes=10),
            "exp": now - timedelta(minutes=5),
        },
        legacy_secret,
        algorithm="HS256",
    )
    rejected = client.post(
        "/refresh", headers={"Authorization": f"Bearer {expired}"}
    )
    assert rejected.status_code == 401
    assert rejected.get_json() == {"msg": "Token has expired"}

    revoked = client.post(
        "/refresh", headers={"Authorization": f"Bearer {revoked_current_token}"}
    )
    assert revoked.status_code == 401
    assert revoked.get_json() == {"msg": "Token has been revoked"}

    revoked_legacy = client.post(
        "/revoke-refresh-token",
        headers={"Authorization": f"Bearer {legacy_token}"},
    )
    assert revoked_legacy.status_code == 200
    assert "legacy-refresh-jti" in revoked_jtis
    rejected_after_revoke = client.post(
        "/refresh", headers={"Authorization": f"Bearer {legacy_token}"}
    )
    assert rejected_after_revoke.status_code == 401
    assert rejected_after_revoke.get_json() == {"msg": "Token has expired"}
