from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
import time
from urllib.parse import urlparse

from commands.dataunions.brainstem.recording_feasibility_study import (
    ASSIGNMENT_POLICY,
    CANDIDATE_PARTICIPANT_INFORMATION,
    COLLECTION_DAYS,
    CONSENT_CONTENT_SHA256,
    CONSENT_VERSION,
    PROTOCOL_VERSION,
    STUDY_ID,
    protocol_sha256,
)
from commands.users.participant_auth import (
    IDENTIFIER,
    SESSION_SECRET,
    ParticipantAuthError,
    checksum_address,
    rfc3339,
    verify_wallet_signature,
)


CHALLENGE_TTL = 300
CHAIN_ID = 11155420
PURPOSE = "brainstem.study.recording-feasibility/action/v1"
RESOURCE = "urn:brainstem:study:recording-feasibility"
ACTIONS = {"enroll", "withdraw"}
WITHDRAWAL_INFORMATION = (
    "You are withdrawing from this Brainstem study. New recordings will no "
    "longer be selected for it. This does not change your other Brainstem "
    "choices."
)


class StudyEnrollmentError(RuntimeError):
    pass


def _sha256(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _scope(action):
    return "participant:self:study:{}".format(action)


def _assignment_start(enrolled_at):
    start = datetime.fromtimestamp(enrolled_at, timezone.utc)
    boundary = start.replace(hour=0, minute=0, second=0, microsecond=0)
    if start != boundary:
        boundary += timedelta(days=1)
    return int(boundary.timestamp())


def _assignment_end(enrolled_at):
    return _assignment_start(enrolled_at) + COLLECTION_DAYS * 24 * 60 * 60


def _valid_sha256(value):
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(char in "0123456789abcdef" for char in value)
    )


def _validated_current(current, user_id):
    fixed = {
        "document_type": "brainstem_study_enrollment",
        "user_id": user_id,
        "study_id": STUDY_ID,
    }
    if (
        not isinstance(current, dict)
        or any(current.get(key) != value for key, value in fixed.items())
        or any(
            not isinstance(current.get(key), str) or not current.get(key)
            for key in (
                "protocol_version",
                "consent_version",
                "assignment_policy",
            )
        )
        or not _valid_sha256(current.get("protocol_sha256"))
        or not _valid_sha256(current.get("consent_content_sha256"))
        or current.get("state") not in {"active", "withdrawn"}
        or any(
            not isinstance(current.get(key), int)
            or isinstance(current.get(key), bool)
            for key in (
                "enrolled_at",
                "assignment_starts_at",
                "assignment_ends_at",
            )
        )
        or current["assignment_starts_at"] < current["enrolled_at"]
        or current["assignment_ends_at"] <= current["assignment_starts_at"]
        or (
            current.get("state") == "active"
            and current.get("withdrawn_at") is not None
        )
        or (
            current.get("state") == "withdrawn"
            and (
                not isinstance(current.get("withdrawn_at"), int)
                or isinstance(current.get("withdrawn_at"), bool)
                or current["withdrawn_at"] < current["enrolled_at"]
            )
        )
    ):
        raise StudyEnrollmentError("enrollment_state_invalid")
    return current


def _enrollment_digest(current):
    keys = (
        "document_type",
        "user_id",
        "study_id",
        "protocol_version",
        "protocol_sha256",
        "consent_version",
        "consent_content_sha256",
        "assignment_policy",
        "state",
        "enrolled_at",
        "assignment_starts_at",
        "assignment_ends_at",
        "withdrawn_at",
    )
    encoded = json.dumps(
        {key: current.get(key) for key in keys},
        sort_keys=True,
        separators=(",", ":"),
    )
    return _sha256(encoded)


def _message(
    origin,
    address,
    action,
    nonce,
    challenge_id,
    issued_at,
    expires_at,
    contract,
    target_enrollment_sha256,
):
    information = (
        CANDIDATE_PARTICIPANT_INFORMATION
        if action == "enroll"
        else WITHDRAWAL_INFORMATION
    )
    target = (
        ["Target Enrollment SHA-256: {}".format(target_enrollment_sha256)]
        if target_enrollment_sha256
        else []
    )
    return "\n".join(
        [
            "{} requests a Brainstem study action with your Ethereum account:".format(
                urlparse(origin).netloc
            ),
            address,
            "",
            information,
            "",
            "URI: {}/participant/studies/recording-feasibility".format(origin),
            "Version: 1",
            "Chain ID: {}".format(CHAIN_ID),
            "Nonce: {}".format(nonce),
            "Issued At: {}".format(rfc3339(issued_at)),
            "Expiration Time: {}".format(rfc3339(expires_at)),
            "Request ID: {}".format(challenge_id),
            "Purpose: {}".format(PURPOSE),
            "Scope: {}".format(_scope(action)),
            "Action: {}".format(action),
            "Study: {}".format(STUDY_ID),
            "Protocol Version: {}".format(contract["protocol_version"]),
            "Protocol SHA-256: {}".format(contract["protocol_sha256"]),
            "Consent Version: {}".format(contract["consent_version"]),
            "Consent Content SHA-256: {}".format(
                contract["consent_content_sha256"]
            ),
            "Assignment Policy: {}".format(contract["assignment_policy"]),
            *target,
            "Payment: none",
            "Resources:",
            "- {}".format(RESOURCE),
        ]
    )


def candidate_action_challenge(
    *,
    user_id,
    address,
    origin,
    action,
    challenge_id,
    nonce,
    current=None,
    now=None,
):
    """Build the exact generated-only action challenge; it is not an API."""
    now = int(time.time() if now is None else now)
    try:
        address = checksum_address(address)
    except ParticipantAuthError as exc:
        raise StudyEnrollmentError("address_invalid") from exc
    if not isinstance(origin, str):
        raise StudyEnrollmentError("origin_invalid")
    parsed = urlparse(origin)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or parsed.path
        or parsed.params
        or parsed.query
        or parsed.fragment
    ):
        raise StudyEnrollmentError("origin_invalid")
    if action not in ACTIONS:
        raise StudyEnrollmentError("action_invalid")
    if not isinstance(user_id, str) or not user_id:
        raise StudyEnrollmentError("participant_invalid")
    if not isinstance(challenge_id, str) or not IDENTIFIER.fullmatch(challenge_id):
        raise StudyEnrollmentError("challenge_invalid")
    if not isinstance(nonce, str) or not SESSION_SECRET.fullmatch(nonce):
        raise StudyEnrollmentError("nonce_invalid")
    if action == "withdraw":
        current = _validated_current(current, user_id)
        contract = {
            "protocol_version": current["protocol_version"],
            "protocol_sha256": current["protocol_sha256"],
            "consent_version": current["consent_version"],
            "consent_content_sha256": current["consent_content_sha256"],
            "assignment_policy": current["assignment_policy"],
        }
        target_enrollment_sha256 = _enrollment_digest(current)
    else:
        contract = {
            "protocol_version": PROTOCOL_VERSION,
            "protocol_sha256": protocol_sha256(),
            "consent_version": CONSENT_VERSION,
            "consent_content_sha256": CONSENT_CONTENT_SHA256,
            "assignment_policy": ASSIGNMENT_POLICY,
        }
        target_enrollment_sha256 = None
    expires_at = now + CHALLENGE_TTL
    message = _message(
        origin,
        address,
        action,
        nonce,
        challenge_id,
        now,
        expires_at,
        contract,
        target_enrollment_sha256,
    )
    return {
        "document_type": "brainstem_study_action_challenge",
        "challenge_id": challenge_id,
        "user_id": user_id,
        "address": address,
        "origin": origin,
        "chain_id": CHAIN_ID,
        "action": action,
        "purpose": PURPOSE,
        "scope": _scope(action),
        "study_id": STUDY_ID,
        **contract,
        "target_enrollment_sha256": target_enrollment_sha256,
        "nonce": nonce,
        "message": message,
        "issued_at": now,
        "expires_at": expires_at,
        "consumed_at": None,
    }


def apply_signed_action(
    challenge,
    current,
    *,
    user_id,
    address,
    origin,
    action,
    signature,
    has_current_data_consent,
    now=None,
):
    """Validate and apply one action; persistence must consume it atomically."""
    now = int(time.time() if now is None else now)
    if not isinstance(origin, str):
        raise StudyEnrollmentError("challenge_unavailable")
    try:
        address = checksum_address(address)
    except ParticipantAuthError as exc:
        raise StudyEnrollmentError("signature_invalid") from exc
    if current is not None:
        current = _validated_current(current, user_id)
    if action == "withdraw":
        if current is None:
            raise StudyEnrollmentError("not_enrolled")
        contract = {
            "protocol_version": current["protocol_version"],
            "protocol_sha256": current["protocol_sha256"],
            "consent_version": current["consent_version"],
            "consent_content_sha256": current["consent_content_sha256"],
            "assignment_policy": current["assignment_policy"],
        }
        target_enrollment_sha256 = _enrollment_digest(current)
    else:
        contract = {
            "protocol_version": PROTOCOL_VERSION,
            "protocol_sha256": protocol_sha256(),
            "consent_version": CONSENT_VERSION,
            "consent_content_sha256": CONSENT_CONTENT_SHA256,
            "assignment_policy": ASSIGNMENT_POLICY,
        }
        target_enrollment_sha256 = None
    exact = {
        "document_type": "brainstem_study_action_challenge",
        "user_id": user_id,
        "address": address,
        "origin": origin,
        "chain_id": CHAIN_ID,
        "action": action,
        "purpose": PURPOSE,
        "scope": _scope(action),
        "study_id": STUDY_ID,
        **contract,
        "target_enrollment_sha256": target_enrollment_sha256,
    }
    issued_at = challenge.get("issued_at") if isinstance(challenge, dict) else None
    expires_at = challenge.get("expires_at") if isinstance(challenge, dict) else None
    if (
        not isinstance(challenge, dict)
        or action not in ACTIONS
        or any(challenge.get(key) != value for key, value in exact.items())
        or challenge.get("consumed_at") is not None
        or not isinstance(issued_at, int)
        or isinstance(issued_at, bool)
        or not isinstance(expires_at, int)
        or isinstance(expires_at, bool)
        or issued_at > now
        or expires_at <= now
        or expires_at - issued_at != CHALLENGE_TTL
        or not isinstance(challenge.get("challenge_id"), str)
        or not IDENTIFIER.fullmatch(challenge["challenge_id"])
        or not isinstance(challenge.get("nonce"), str)
        or not SESSION_SECRET.fullmatch(challenge["nonce"])
    ):
        raise StudyEnrollmentError("challenge_unavailable")
    expected_message = _message(
        origin,
        address,
        action,
        challenge["nonce"],
        challenge["challenge_id"],
        issued_at,
        expires_at,
        contract,
        target_enrollment_sha256,
    )
    if not isinstance(challenge.get("message"), str) or not hmac.compare_digest(
        challenge["message"], expected_message
    ):
        raise StudyEnrollmentError("challenge_unavailable")
    try:
        verify_wallet_signature(expected_message, signature, address)
    except ParticipantAuthError as exc:
        raise StudyEnrollmentError("signature_invalid") from exc

    changed = False
    if action == "enroll":
        if has_current_data_consent is not True:
            raise StudyEnrollmentError("current_data_consent_required")
        if current is not None and current["state"] == "withdrawn":
            raise StudyEnrollmentError("withdrawal_is_terminal")
        if current is not None and any(
            current.get(key) != value for key, value in contract.items()
        ):
            raise StudyEnrollmentError("already_enrolled_other_version")
        if current is None:
            current = {
                "document_type": "brainstem_study_enrollment",
                "user_id": user_id,
                "study_id": STUDY_ID,
                "protocol_version": PROTOCOL_VERSION,
                "protocol_sha256": protocol_sha256(),
                "consent_version": CONSENT_VERSION,
                "consent_content_sha256": CONSENT_CONTENT_SHA256,
                "assignment_policy": ASSIGNMENT_POLICY,
                "state": "active",
                "enrolled_at": now,
                "assignment_starts_at": _assignment_start(now),
                "assignment_ends_at": _assignment_end(now),
                "enrollment_message_sha256": _sha256(expected_message),
                "withdrawn_at": None,
            }
            changed = True
    elif current["state"] == "active":
        current = dict(current)
        current["state"] = "withdrawn"
        current["withdrawn_at"] = now
        current["withdrawal_message_sha256"] = _sha256(expected_message)
        changed = True

    consumed = dict(challenge)
    consumed["message_sha256"] = _sha256(consumed.pop("message"))
    consumed["address_sha256"] = _sha256(consumed.pop("address").lower())
    consumed["nonce_sha256"] = _sha256(consumed.pop("nonce"))
    consumed["consumed_at"] = now
    return consumed, current, changed
