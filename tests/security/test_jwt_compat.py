from datetime import datetime, timedelta, timezone

import jwt
from flask import Flask, jsonify
from flask_jwt_extended import JWTManager, create_access_token, jwt_required

from security.jwt_compat import client_token_error, decode_legacy_refresh


def test_legacy_refresh_is_narrow_and_expiring():
    secret = "test-" * 8
    now = datetime.now(timezone.utc)
    claims = {
        "sub": "0x1111111111111111111111111111111111111111",
        "type": "refresh",
        "source": "brainstem",
        "jti": "test-jti",
        "iat": now,
        "nbf": now,
        "exp": now + timedelta(minutes=5),
    }
    token = jwt.encode(claims, secret, algorithm="HS256")

    assert decode_legacy_refresh(token, secret, "brainstem")["sub"] == claims["sub"]
    assert decode_legacy_refresh(token, "wrong-secret-that-also-has-32-bytes", "brainstem") is None
    assert decode_legacy_refresh(token, secret, "another-dataunion") is None

    access = jwt.encode({**claims, "type": "access"}, secret, algorithm="HS256")
    assert decode_legacy_refresh(access, secret, "brainstem") is None

    expired = jwt.encode({**claims, "exp": now - timedelta(seconds=1)}, secret, algorithm="HS256")
    assert decode_legacy_refresh(expired, secret, "brainstem") is None

    assert client_token_error("Signature verification failed") == ("Token has expired", 401)
    assert client_token_error("Only refresh tokens are allowed") == (
        "Only refresh tokens are allowed",
        422,
    )


def test_invalid_old_access_token_tells_installed_client_to_refresh():
    application = Flask(__name__)
    application.config["JWT_SECRET_KEY"] = "current-test-secret-that-has-32-bytes"
    jwt_manager = JWTManager(application)

    @jwt_manager.invalid_token_loader
    def invalid_token(reason):
        message, status = client_token_error(reason)
        return jsonify({"msg": message}), status

    @application.get("/protected")
    @jwt_required()
    def protected():
        return jsonify({"ok": True})

    with application.app_context():
        current_token = create_access_token(identity="0x123")

    legacy_claims = {
        "sub": "0x123",
        "type": "access",
        "jti": "legacy-access",
        "iat": datetime.now(timezone.utc),
        "nbf": datetime.now(timezone.utc),
        "exp": datetime.now(timezone.utc) + timedelta(minutes=5),
    }
    legacy_token = jwt.encode(
        legacy_claims,
        "legacy-test-secret-that-also-has-32-bytes",
        algorithm="HS256",
    )

    client = application.test_client()
    assert client.get(
        "/protected", headers={"Authorization": f"Bearer {current_token}"}
    ).status_code == 200
    rejected = client.get(
        "/protected", headers={"Authorization": f"Bearer {legacy_token}"}
    )
    assert rejected.status_code == 401
    assert rejected.get_json() == {"msg": "Token has expired"}
