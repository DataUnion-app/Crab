import hashlib
import hmac
import re
import secrets
import time
import uuid
from datetime import datetime, timezone
from urllib.parse import urlparse

from eth_account import Account
from eth_account.messages import encode_defunct
from eth_keys.exceptions import BadSignature
from web3 import Web3

from dao.sessions_dao import ParticipantSessionStateError


ADDRESS = re.compile(r"^0x[0-9a-fA-F]{40}$")
SIGNATURE = re.compile(r"^0x[0-9a-fA-F]{130}$")
IDENTIFIER = re.compile(r"^[0-9a-f]{32}$")
SESSION_SECRET = re.compile(r"^[A-Za-z0-9_-]{43}$")
PURPOSE = "brainstem.participant.web-login"
SCOPE = "participant:self:status:read"
RESOURCE = "urn:brainstem:scope:participant:self:status:read"
STATEMENT = (
    "Confirm this Brainstem app belongs to you. This cannot authorize a "
    "transaction, study enrollment, compute, data change, or payment."
)


class ParticipantAuthError(Exception):
    def __init__(self, message, status_code=400):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def rfc3339(timestamp):
    return (
        datetime.fromtimestamp(timestamp, timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


def checksum_address(value):
    if not isinstance(value, str) or not ADDRESS.fullmatch(value):
        raise ParticipantAuthError("A valid wallet address is required")
    try:
        return Web3.to_checksum_address(value)
    except ValueError:
        raise ParticipantAuthError("A valid wallet address is required")


def validate_origin(value, allowed_origins):
    if not isinstance(value, str):
        raise ParticipantAuthError("Participant origin is required", 403)
    value = value.rstrip("/")
    parsed = urlparse(value)
    if (
        value not in allowed_origins
        or parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or parsed.path
        or parsed.params
        or parsed.query
        or parsed.fragment
    ):
        raise ParticipantAuthError("Participant origin is not allowed", 403)
    return value


def _message(origin, address, chain_id, nonce, challenge_id, issued_at, expires_at):
    domain = urlparse(origin).netloc
    return "\n".join(
        [
            "{} wants you to sign in with your Ethereum account:".format(domain),
            address,
            "",
            STATEMENT,
            "",
            "URI: {}/participant".format(origin),
            "Version: 1",
            "Chain ID: {}".format(chain_id),
            "Nonce: {}".format(nonce),
            "Issued At: {}".format(rfc3339(issued_at)),
            "Expiration Time: {}".format(rfc3339(expires_at)),
            "Request ID: {}".format(challenge_id),
            "Purpose: {}".format(PURPOSE),
            "Resources:",
            "- {}".format(RESOURCE),
        ]
    )


def _slot(kind, origin, identity):
    return hashlib.sha256(
        "{}\0{}\0{}".format(kind, origin, identity).encode("utf-8")
    ).hexdigest()[:32]


def verify_wallet_signature(message, signature, address):
    if not isinstance(signature, str) or not SIGNATURE.fullmatch(signature):
        raise ParticipantAuthError("A valid wallet signature is required")
    try:
        recovered = Account.recover_message(
            encode_defunct(text=message), signature=signature
        )
    except (BadSignature, ValueError, TypeError):
        raise ParticipantAuthError("Signature is invalid", 401)
    if recovered.lower() != address.lower():
        raise ParticipantAuthError("Signature is invalid", 401)


class ParticipantAuthService:
    def __init__(
        self,
        sessions,
        users,
        allowed_origins,
        chain_id=11155420,
        challenge_ttl=300,
        session_ttl=900,
        clock=time.time,
        nonce_factory=lambda: secrets.token_urlsafe(32),
        id_factory=lambda: uuid.uuid4().hex,
        secret_factory=lambda: secrets.token_urlsafe(32),
    ):
        self.sessions = sessions
        self.users = users
        self.allowed_origins = tuple(origin.rstrip("/") for origin in allowed_origins)
        self.chain_id = int(chain_id)
        self.challenge_ttl = int(challenge_ttl)
        self.session_ttl = int(session_ttl)
        self.clock = clock
        self.nonce_factory = nonce_factory
        self.id_factory = id_factory
        self.secret_factory = secret_factory
        if not self.allowed_origins:
            raise ParticipantAuthError("Participant authentication is disabled", 503)
        if not 1 <= self.challenge_ttl <= 600 or not 1 <= self.session_ttl <= 3600:
            raise ValueError("Participant authentication TTL is outside the safe range")

    def create_challenge(self, address, origin):
        origin = validate_origin(origin, self.allowed_origins)
        address = checksum_address(address)
        challenge_id = self.id_factory()
        if not IDENTIFIER.fullmatch(challenge_id):
            raise RuntimeError("Invalid challenge identifier")
        issued_at = int(self.clock())
        expires_at = issued_at + self.challenge_ttl
        message = _message(
            origin,
            address,
            self.chain_id,
            self.nonce_factory(),
            challenge_id,
            issued_at,
            expires_at,
        )
        challenge = {
            "document_type": "participant_auth_challenge",
            "challenge_id": challenge_id,
            "address": address,
            "origin": origin,
            "purpose": PURPOSE,
            "scope": SCOPE,
            "message": message,
            "issued_at": issued_at,
            "expires_at": expires_at,
            "consumed_at": None,
        }
        users = self.users.get_by_public_address(address).get("result", [])
        if len(users) == 1 and not users[0].get("is_access_blocked"):
            try:
                challenge = self.sessions.create_participant_challenge(
                    _slot("challenge", origin, address), challenge, issued_at
                )
            except ParticipantSessionStateError:
                pass
        return {
            "challengeId": challenge["challenge_id"],
            "message": challenge["message"],
            "expiresAt": rfc3339(challenge["expires_at"]),
            "chainId": self.chain_id,
            "method": "personal_sign",
        }

    def create_session(self, challenge_id, address, signature, origin):
        origin = validate_origin(origin, self.allowed_origins)
        if not isinstance(challenge_id, str) or not IDENTIFIER.fullmatch(challenge_id):
            raise ParticipantAuthError("A valid challenge is required")
        address = checksum_address(address)
        challenge_slot = _slot("challenge", origin, address)
        try:
            challenge = self.sessions.get_participant_challenge(
                challenge_slot, challenge_id
            )
        except ParticipantSessionStateError:
            raise ParticipantAuthError("Challenge is unavailable", 401)
        now = int(self.clock())
        if challenge.get("expires_at", 0) <= now:
            raise ParticipantAuthError("Challenge expired", 410)
        if (
            challenge.get("address") != address
            or challenge.get("challenge_id") != challenge_id
            or challenge.get("origin") != origin
            or challenge.get("purpose") != PURPOSE
            or challenge.get("scope") != SCOPE
            or challenge.get("consumed_at") is not None
        ):
            status = 409 if challenge.get("consumed_at") is not None else 401
            raise ParticipantAuthError("Challenge is unavailable", status)
        verify_wallet_signature(challenge["message"], signature, address)

        users = self.users.get_by_public_address(address).get("result", [])
        if len(users) != 1 or users[0].get("is_access_blocked"):
            raise ParticipantAuthError("Participant session is unavailable", 401)
        try:
            self.sessions.consume_participant_challenge(
                challenge_slot, challenge_id, now
            )
        except ParticipantSessionStateError as error:
            status = 410 if "expired" in str(error).lower() else 409
            raise ParticipantAuthError(str(error), status)

        session_id = _slot("session", origin, users[0]["_id"])
        secret = self.secret_factory()
        if not IDENTIFIER.fullmatch(session_id) or not SESSION_SECRET.fullmatch(secret):
            raise RuntimeError("Invalid participant session credential")
        token = "{}.{}".format(session_id, secret)
        expires_at = now + self.session_ttl
        self.sessions.create_or_replace_participant_session(
            session_id,
            {
                "document_type": "participant_auth_session",
                "user_id": users[0]["_id"],
                "token_sha256": hashlib.sha256(token.encode("ascii")).hexdigest(),
                "scope": SCOPE,
                "origin": origin,
                "issued_at": now,
                "expires_at": expires_at,
                "revoked_at": None,
            },
        )
        return {"token": token, "expiresAt": rfc3339(expires_at), "scope": SCOPE}

    def authenticate(self, token, origin):
        origin = validate_origin(origin, self.allowed_origins)
        if not isinstance(token, str) or token.count(".") != 1:
            raise ParticipantAuthError("Participant session is invalid", 401)
        session_id, secret = token.split(".", 1)
        if not IDENTIFIER.fullmatch(session_id) or not SESSION_SECRET.fullmatch(secret):
            raise ParticipantAuthError("Participant session is invalid", 401)
        try:
            session = self.sessions.get_participant_session(session_id)
        except ParticipantSessionStateError:
            raise ParticipantAuthError("Participant session is invalid", 401)
        expected = session.get("token_sha256", "")
        actual = hashlib.sha256(token.encode("ascii")).hexdigest()
        if (
            not hmac.compare_digest(expected, actual)
            or session.get("origin") != origin
            or session.get("scope") != SCOPE
            or session.get("revoked_at") is not None
            or session.get("expires_at", 0) <= int(self.clock())
        ):
            raise ParticipantAuthError("Participant session is invalid", 401)
        try:
            user = self.users.get_doc_by_id(session["user_id"])
        except Exception:
            raise ParticipantAuthError("Participant session is invalid", 401)
        if user.get("is_access_blocked"):
            raise ParticipantAuthError("Participant session is invalid", 401)
        return session_id, session, user

    def self_status(self, token, origin):
        _session_id, session, user = self.authenticate(token, origin)
        return {
            "schema": "brainstem.participant-self-status/v1",
            "authenticated": True,
            "consent": {
                "dataUse": user.get("usage_flag", "UNKNOWN"),
                "guidelines": user.get("guidelines_acceptance_flag", "UNKNOWN"),
            },
            "scope": session["scope"],
            "expiresAt": rfc3339(session["expires_at"]),
        }

    def logout(self, token, origin):
        session_id, _session, _user = self.authenticate(token, origin)
        self.sessions.revoke_participant_session(session_id, int(self.clock()))
