import jwt


def client_token_error(reason):
    if reason == "Signature verification failed":
        return "Token has expired", 401
    return reason, 422


def decode_legacy_refresh(token, secret, expected_source):
    if not token or not secret:
        return None
    try:
        payload = jwt.decode(
            token,
            secret,
            algorithms=["HS256"],
            options={"require": ["exp", "iat", "jti", "nbf", "sub", "type"]},
        )
    except jwt.InvalidTokenError:
        return None

    if payload.get("type") != "refresh" or payload.get("source") != expected_source:
        return None
    return payload
