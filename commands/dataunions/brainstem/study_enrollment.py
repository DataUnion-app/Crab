from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
import secrets
import time
import uuid
from urllib.parse import urlparse

from commands.dataunions.brainstem.study_contract import (
    ASSIGNMENT_VERSION,
    COLLECTION_DAYS,
    CONSENT_VERSION,
    PARTICIPANT_INFORMATION,
    PROTOCOL_VERSION,
    STUDY_ID,
    SURVEY_VERSION,
    consent_sha256,
    protocol_sha256,
    survey_sha256,
)
from commands.users.participant_auth import (
    IDENTIFIER,
    SESSION_SECRET,
    ParticipantAuthError,
    checksum_address,
    rfc3339,
    verify_wallet_signature,
)


CHAIN_ID = 11155420
CHALLENGE_TTL = 300
PURPOSE = "brainstem.study.recording-feasibility/action/v1"
RESOURCE = "urn:brainstem:study:recording-feasibility"
ACTIONS = {"survey", "enroll", "withdraw"}


class StudyEnrollmentError(RuntimeError):
    pass


def _sha256(value) -> str:
    encoded = (
        value.encode()
        if isinstance(value, str)
        else json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    )
    return hashlib.sha256(encoded).hexdigest()


def _valid_hash(value) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _start(now) -> int:
    value = datetime.fromtimestamp(now, timezone.utc)
    boundary = value.replace(hour=0, minute=0, second=0, microsecond=0)
    if value != boundary:
        boundary += timedelta(days=1)
    return int(boundary.timestamp())


def enrollment_sha256(value) -> str:
    keys = (
        "studyId",
        "protocolVersion",
        "protocolSha256",
        "surveyVersion",
        "surveySha256",
        "surveyRevisionSha256",
        "consentVersion",
        "consentSha256",
        "assignmentVersion",
        "state",
        "enrollmentRevision",
        "enrolledAt",
        "startsAt",
        "endsAt",
        "withdrawnAt",
    )
    return _sha256({key: value.get(key) for key in keys})


def _validate_enrollment(value) -> dict:
    if (
        not isinstance(value, dict)
        or value.get("schema") != "brainstem.study-enrollment/v1"
        or value.get("studyId") != STUDY_ID
        or value.get("state")
        not in {"active", "renewal_required", "withdrawn"}
        or not isinstance(value.get("enrollmentRevision"), int)
        or isinstance(value.get("enrollmentRevision"), bool)
        or value["enrollmentRevision"] < 1
        or not all(
            _valid_hash(value.get(key))
            for key in (
                "protocolSha256",
                "surveySha256",
                "surveyRevisionSha256",
                "consentSha256",
            )
        )
        or not all(
            isinstance(value.get(key), int)
            and not isinstance(value.get(key), bool)
            for key in ("enrolledAt", "startsAt", "endsAt")
        )
        or value["endsAt"] - value["startsAt"] != COLLECTION_DAYS * 86400
    ):
        raise StudyEnrollmentError("enrollment_invalid")
    return value


def mark_survey_corrected(current, survey_revision_sha256, *, changed_at) -> dict:
    current = _validate_enrollment(current)
    if not _valid_hash(survey_revision_sha256):
        raise StudyEnrollmentError("survey_revision_invalid")
    if (
        current["state"] != "active"
        or current["surveyRevisionSha256"] == survey_revision_sha256
    ):
        return current
    result = dict(current)
    result["state"] = "renewal_required"
    result["renewalRequiredAt"] = changed_at
    return result


def _contract(survey_revision) -> dict:
    if (
        not isinstance(survey_revision, dict)
        or survey_revision.get("state") != "active"
        or survey_revision.get("eligibility", {}).get("status") != "eligible"
        or not _valid_hash(survey_revision.get("revisionSha256"))
    ):
        raise StudyEnrollmentError("eligible_survey_required")
    return {
        "protocolVersion": PROTOCOL_VERSION,
        "protocolSha256": protocol_sha256(),
        "surveyVersion": SURVEY_VERSION,
        "surveySha256": survey_sha256(),
        "surveyRevisionSha256": survey_revision["revisionSha256"],
        "consentVersion": CONSENT_VERSION,
        "consentSha256": consent_sha256(),
        "assignmentVersion": ASSIGNMENT_VERSION,
    }


def _survey_contract(survey_revision) -> dict:
    if (
        not isinstance(survey_revision, dict)
        or survey_revision.get("state") != "active"
        or not _valid_hash(survey_revision.get("revisionSha256"))
    ):
        raise StudyEnrollmentError("survey_revision_invalid")
    return {
        "protocolVersion": PROTOCOL_VERSION,
        "protocolSha256": protocol_sha256(),
        "surveyVersion": SURVEY_VERSION,
        "surveySha256": survey_sha256(),
        "surveyRevisionSha256": survey_revision["revisionSha256"],
        "consentVersion": CONSENT_VERSION,
        "consentSha256": consent_sha256(),
        "assignmentVersion": ASSIGNMENT_VERSION,
    }


def _message(
    origin,
    address,
    action,
    nonce,
    challenge_id,
    issued_at,
    expires_at,
    contract,
    target,
):
    statement = {
        "survey": (
            "Save these self-reported answers for this candidate Brainstem "
            "study. This does not enroll you or authorize data use."
        ),
        "enroll": PARTICIPANT_INFORMATION,
        "withdraw": (
            "Withdraw from this Brainstem study. New recordings will no longer "
            "be selected. This does not change your other Brainstem choices."
        ),
    }[action]
    lines = [
        "{} requests a Brainstem study action with your Ethereum account:".format(
            urlparse(origin).netloc
        ),
        address,
        "",
        statement,
        "",
        "URI: {}/participant/studies/recording-feasibility".format(origin),
        "Version: 1",
        "Chain ID: {}".format(CHAIN_ID),
        "Nonce: {}".format(nonce),
        "Issued At: {}".format(rfc3339(issued_at)),
        "Expiration Time: {}".format(rfc3339(expires_at)),
        "Request ID: {}".format(challenge_id),
        "Purpose: {}".format(PURPOSE),
        "Scope: participant:self:study:{}".format(action),
        "Action: {}".format(action),
        "Study: {}".format(STUDY_ID),
        "Protocol Version: {}".format(contract["protocolVersion"]),
        "Protocol SHA256: {}".format(contract["protocolSha256"]),
        "Survey Version: {}".format(contract["surveyVersion"]),
        "Survey SHA256: {}".format(contract["surveySha256"]),
        "Survey Revision SHA256: {}".format(contract["surveyRevisionSha256"]),
        "Consent Version: {}".format(contract["consentVersion"]),
        "Consent SHA256: {}".format(contract["consentSha256"]),
        "Assignment Version: {}".format(contract["assignmentVersion"]),
    ]
    if target:
        lines.append("Target Enrollment SHA256: {}".format(target))
    lines.extend(["Payment: none", "Resources:", "- {}".format(RESOURCE)])
    return "\n".join(lines)


def create_action_challenge(
    *,
    user_id,
    address,
    origin,
    action,
    survey_revision,
    current=None,
    now=None,
    challenge_id_factory=lambda: uuid.uuid4().hex,
    nonce_factory=lambda: secrets.token_urlsafe(32),
) -> dict:
    now = int(time.time() if now is None else now)
    try:
        address = checksum_address(address)
    except ParticipantAuthError as error:
        raise StudyEnrollmentError("address_invalid") from error
    parsed = urlparse(origin) if isinstance(origin, str) else None
    if (
        not parsed
        or parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or parsed.path
        or parsed.query
        or parsed.fragment
    ):
        raise StudyEnrollmentError("origin_invalid")
    if action not in ACTIONS:
        raise StudyEnrollmentError("action_invalid")
    if not isinstance(user_id, str) or not user_id:
        raise StudyEnrollmentError("participant_invalid")
    if action == "withdraw":
        current = _validate_enrollment(current)
        contract = {
            key: current[key]
            for key in (
                "protocolVersion",
                "protocolSha256",
                "surveyVersion",
                "surveySha256",
                "surveyRevisionSha256",
                "consentVersion",
                "consentSha256",
                "assignmentVersion",
            )
        }
        target = enrollment_sha256(current)
    elif action == "enroll":
        contract = _contract(survey_revision)
        target = None
    else:
        contract = _survey_contract(survey_revision)
        target = None
    challenge_id = challenge_id_factory()
    nonce = nonce_factory()
    if not IDENTIFIER.fullmatch(challenge_id) or not SESSION_SECRET.fullmatch(nonce):
        raise RuntimeError("invalid generated study challenge")
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
        target,
    )
    return {
        "schema": "brainstem.study-action-challenge/v1",
        "challengeId": challenge_id,
        "userId": user_id,
        "address": address,
        "origin": origin,
        "action": action,
        "studyId": STUDY_ID,
        **contract,
        "targetEnrollmentSha256": target,
        "nonce": nonce,
        "message": message,
        "issuedAt": now,
        "expiresAt": expires_at,
        "consumedAt": None,
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
    survey_revision,
    current_data_consent,
    now=None,
):
    now = int(time.time() if now is None else now)
    try:
        address = checksum_address(address)
    except ParticipantAuthError as error:
        raise StudyEnrollmentError("signature_invalid") from error
    if action == "withdraw":
        current = _validate_enrollment(current)
        contract = {
            key: current[key]
            for key in (
                "protocolVersion",
                "protocolSha256",
                "surveyVersion",
                "surveySha256",
                "surveyRevisionSha256",
                "consentVersion",
                "consentSha256",
                "assignmentVersion",
            )
        }
        target = enrollment_sha256(current)
    elif action == "enroll":
        contract = _contract(survey_revision)
        target = None
    else:
        contract = _survey_contract(survey_revision)
        target = None
    exact = {
        "schema": "brainstem.study-action-challenge/v1",
        "userId": user_id,
        "address": address,
        "origin": origin,
        "action": action,
        "studyId": STUDY_ID,
        **contract,
        "targetEnrollmentSha256": target,
    }
    if (
        not isinstance(challenge, dict)
        or any(challenge.get(key) != value for key, value in exact.items())
        or challenge.get("consumedAt") is not None
        or not isinstance(challenge.get("issuedAt"), int)
        or not isinstance(challenge.get("expiresAt"), int)
        or challenge["issuedAt"] > now
        or challenge["expiresAt"] <= now
        or challenge["expiresAt"] - challenge["issuedAt"] != CHALLENGE_TTL
    ):
        raise StudyEnrollmentError("challenge_unavailable")
    expected = _message(
        origin,
        address,
        action,
        challenge["nonce"],
        challenge["challengeId"],
        challenge["issuedAt"],
        challenge["expiresAt"],
        contract,
        target,
    )
    if not hmac.compare_digest(challenge.get("message", ""), expected):
        raise StudyEnrollmentError("challenge_unavailable")
    try:
        verify_wallet_signature(expected, signature, address)
    except ParticipantAuthError as error:
        raise StudyEnrollmentError("signature_invalid") from error

    if action == "enroll":
        if current_data_consent is not True:
            raise StudyEnrollmentError("current_data_consent_required")
        if current is not None:
            current = _validate_enrollment(current)
            if current["state"] == "withdrawn":
                raise StudyEnrollmentError("withdrawal_is_terminal")
            if (
                current["state"] == "active"
                and current["surveyRevisionSha256"]
                == contract["surveyRevisionSha256"]
            ):
                enrollment = current
            elif current["state"] != "renewal_required":
                raise StudyEnrollmentError("enrollment_conflict")
            else:
                start = _start(now)
                enrollment = _new_enrollment(
                    contract,
                    now,
                    start,
                    current["enrollmentRevision"] + 1,
                    enrollment_sha256(current),
                )
        else:
            start = _start(now)
            enrollment = _new_enrollment(contract, now, start, 1, None)
    elif action == "withdraw":
        enrollment = dict(current)
        if enrollment["state"] != "withdrawn":
            enrollment["state"] = "withdrawn"
            enrollment["withdrawnAt"] = now
    else:
        enrollment = current
    consumed = {
        "schema": "brainstem.study-action-receipt/v1",
        "challengeId": challenge["challengeId"],
        "action": action,
        "studyId": STUDY_ID,
        "issuedAt": challenge["issuedAt"],
        "expiresAt": challenge["expiresAt"],
        "consumedAt": now,
    }
    return consumed, enrollment


def _new_enrollment(contract, now, start, revision, supersedes):
    return {
        "schema": "brainstem.study-enrollment/v1",
        "studyId": STUDY_ID,
        **contract,
        "state": "active",
        "enrollmentRevision": revision,
        "enrolledAt": now,
        "startsAt": start,
        "endsAt": start + COLLECTION_DAYS * 86400,
        "withdrawnAt": None,
        "supersedes": supersedes,
    }
