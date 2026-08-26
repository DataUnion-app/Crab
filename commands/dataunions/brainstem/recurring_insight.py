import hashlib
import hmac
import json
import secrets
import time
import uuid
from urllib.parse import urlparse

from commands.dataunions.brainstem.personal_insight import (
    DIGEST_PATTERN,
    PersonalInsightPolicy,
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
SCOPE = "participant:self:insight:recurring"
PURPOSE = "brainstem.personal-insight.recurring-authorization/v1"
RESOURCE = "urn:brainstem:scope:participant:self:insight:recurring"
ACTIONS = {"activate", "pause", "resume", "revoke", "delete"}
CADENCES = {1, 7, 30}


class RecurringInsightError(RuntimeError):
    pass


def _sha256(value):
    raw = (
        value.encode()
        if isinstance(value, str)
        else json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    )
    return hashlib.sha256(raw).hexdigest()


def _binding(policy, algorithm_image_digest):
    if (
        not isinstance(policy, PersonalInsightPolicy)
        or DIGEST_PATTERN.fullmatch(algorithm_image_digest or "") is None
    ):
        raise RecurringInsightError("insight_contract_invalid")
    return {
        "analysisId": policy.analysis_id,
        "algorithmVersion": policy.algorithm_version,
        "algorithmImageDigest": algorithm_image_digest,
        "inputSchema": policy.input_schema,
        "inputPolicy": policy.input_policy,
        "resultSchema": policy.result_schema,
        "resultProfile": policy.result_profile,
        "approvedManifestSha256": policy.approved_manifest_sha256,
        "referenceSha256": policy.reference_sha256,
        "evidenceTier": policy.evidence_tier,
        "useClass": policy.use_class,
        "clinicalUse": "prohibited",
    }


def recurring_settings(value):
    if (
        not isinstance(value, dict)
        or set(value)
        != {
            "cadenceDays",
            "maximumRunsPer30Days",
            "maximumChargeMinor",
            "currency",
            "notification",
            "retentionDays",
            "minimumNewRecordings",
            "startsAt",
            "expiresAt",
            "entitlement",
        }
        or value["cadenceDays"] not in CADENCES
        or not isinstance(value["maximumRunsPer30Days"], int)
        or isinstance(value["maximumRunsPer30Days"], bool)
        or not 0 <= value["maximumRunsPer30Days"] <= 31
        or value["maximumChargeMinor"] != 0
        or value["currency"] != "none"
        or value["notification"] != "in_app"
        or not isinstance(value["retentionDays"], int)
        or isinstance(value["retentionDays"], bool)
        or not 1 <= value["retentionDays"] <= 14
        or not isinstance(value["minimumNewRecordings"], int)
        or isinstance(value["minimumNewRecordings"], bool)
        or not 1 <= value["minimumNewRecordings"] <= 16
        or not isinstance(value["startsAt"], int)
        or isinstance(value["startsAt"], bool)
        or not isinstance(value["expiresAt"], int)
        or isinstance(value["expiresAt"], bool)
        or not value["startsAt"] < value["expiresAt"] <= value["startsAt"] + 365 * 86400
        or value["entitlement"] != "no_charge"
    ):
        raise RecurringInsightError("recurring_settings_invalid")
    return dict(value)


def authorization_sha256(value):
    return _sha256(
        {
            key: value.get(key)
            for key in (
                "schema",
                "userId",
                "origin",
                "state",
                "revision",
                "binding",
                "settings",
                "activatedAt",
                "pausedAt",
                "revokedAt",
            )
        }
    )


def _message(
    origin,
    address,
    action,
    challenge_id,
    nonce,
    issued_at,
    expires_at,
    binding,
    settings,
    target,
):
    lines = [
        "{} requests a recurring Brainstem Insight action with your Ethereum account:".format(
            urlparse(origin).netloc
        ),
        address,
        "",
        (
            "Allow repeated private Insight runs only under the limits below. "
            "This is separate from one-time approval and is not a diagnosis, "
            "medical advice, payment, study enrollment, or data sharing."
        ),
        "",
        "URI: {}/participant/insights/settings".format(origin),
        "Version: 1",
        "Chain ID: {}".format(CHAIN_ID),
        "Nonce: {}".format(nonce),
        "Issued At: {}".format(rfc3339(issued_at)),
        "Expiration Time: {}".format(rfc3339(expires_at)),
        "Request ID: {}".format(challenge_id),
        "Purpose: {}".format(PURPOSE),
        "Scope: {}".format(SCOPE),
        "Action: {}".format(action),
        "Insight: {}".format(binding["analysisId"]),
        "Algorithm Version: {}".format(binding["algorithmVersion"]),
        "Algorithm Image Digest: {}".format(binding["algorithmImageDigest"]),
        "Approved Manifest SHA256: {}".format(
            binding["approvedManifestSha256"] or "none"
        ),
        "Cohort Reference SHA256: {}".format(binding["referenceSha256"] or "none"),
        "Cadence Days: {}".format(settings["cadenceDays"]),
        "Maximum Runs Per 30 Days: {}".format(
            settings["maximumRunsPer30Days"]
        ),
        "Maximum Charge Minor: 0",
        "Currency: none",
        "Notification: in_app",
        "Retention Days: {}".format(settings["retentionDays"]),
        "Minimum New Recordings: {}".format(settings["minimumNewRecordings"]),
        "Starts At: {}".format(rfc3339(settings["startsAt"])),
        "Expires At: {}".format(rfc3339(settings["expiresAt"])),
        "Entitlement: no_charge",
    ]
    if target:
        lines.append("Target Authorization SHA256: {}".format(target))
    lines.extend(["Resources:", "- {}".format(RESOURCE)])
    return "\n".join(lines)


def create_challenge(
    *,
    user_id,
    address,
    origin,
    action,
    policy,
    algorithm_image_digest,
    settings,
    current=None,
    now=None,
    challenge_id_factory=lambda: uuid.uuid4().hex,
    nonce_factory=lambda: secrets.token_urlsafe(32),
):
    now = int(time.time() if now is None else now)
    try:
        address = checksum_address(address)
    except ParticipantAuthError as error:
        raise RecurringInsightError("address_invalid") from error
    parsed = urlparse(origin) if isinstance(origin, str) else None
    if (
        not parsed
        or parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or parsed.path
        or parsed.query
        or parsed.fragment
        or action not in ACTIONS
        or not isinstance(user_id, str)
        or not user_id
    ):
        raise RecurringInsightError("challenge_request_invalid")
    binding = _binding(policy, algorithm_image_digest)
    settings = recurring_settings(settings)
    target = None
    if action == "activate" and current is not None:
        validate_authorization(current)
        target = authorization_sha256(current)
    elif action != "activate":
        validate_authorization(current)
        if current["state"] in {"revoked", "deleted"}:
            raise RecurringInsightError("authorization_terminal")
        binding = current["binding"]
        settings = current["settings"]
        target = authorization_sha256(current)
    challenge_id = challenge_id_factory()
    nonce = nonce_factory()
    if not IDENTIFIER.fullmatch(challenge_id) or not SESSION_SECRET.fullmatch(nonce):
        raise RuntimeError("invalid generated recurring challenge")
    expires_at = now + CHALLENGE_TTL
    message = _message(
        origin,
        address,
        action,
        challenge_id,
        nonce,
        now,
        expires_at,
        binding,
        settings,
        target,
    )
    return {
        "schema": "brainstem.recurring-insight-challenge/v1",
        "challengeId": challenge_id,
        "userId": user_id,
        "address": address,
        "origin": origin,
        "action": action,
        "binding": binding,
        "settings": settings,
        "targetAuthorizationSha256": target,
        "nonce": nonce,
        "message": message,
        "issuedAt": now,
        "expiresAt": expires_at,
        "consumedAt": None,
    }


def validate_authorization(value):
    if (
        isinstance(value, dict)
        and value.get("schema") == "brainstem.recurring-insight-authorization/v1"
        and value.get("state") == "deleted"
        and isinstance(value.get("revision"), int)
        and not isinstance(value.get("revision"), bool)
        and value["revision"] >= 1
        and isinstance(value.get("userIdHash"), str)
        and len(value["userIdHash"]) == 64
        and isinstance(value.get("authorizationSha256"), str)
        and len(value["authorizationSha256"]) == 64
    ):
        return value
    if (
        not isinstance(value, dict)
        or value.get("schema") != "brainstem.recurring-insight-authorization/v1"
        or value.get("state")
        not in {"active", "paused", "renewal_required", "revoked"}
        or not isinstance(value.get("revision"), int)
        or isinstance(value.get("revision"), bool)
        or value["revision"] < 1
        or not isinstance(value.get("binding"), dict)
    ):
        raise RecurringInsightError("authorization_invalid")
    recurring_settings(value.get("settings"))
    return value


def apply_signed_action(
    challenge,
    current,
    *,
    user_id,
    address,
    origin,
    action,
    signature,
    now=None,
):
    now = int(time.time() if now is None else now)
    try:
        address = checksum_address(address)
    except ParticipantAuthError as error:
        raise RecurringInsightError("signature_invalid") from error
    if action != "activate" or current is not None:
        validate_authorization(current)
    expected_target = (
        authorization_sha256(current) if current is not None else None
    )
    exact = {
        "schema": "brainstem.recurring-insight-challenge/v1",
        "userId": user_id,
        "address": address,
        "origin": origin,
        "action": action,
        "targetAuthorizationSha256": expected_target,
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
        raise RecurringInsightError("challenge_unavailable")
    expected = _message(
        origin,
        address,
        action,
        challenge["challengeId"],
        challenge["nonce"],
        challenge["issuedAt"],
        challenge["expiresAt"],
        challenge["binding"],
        challenge["settings"],
        expected_target,
    )
    if not hmac.compare_digest(challenge.get("message", ""), expected):
        raise RecurringInsightError("challenge_unavailable")
    try:
        verify_wallet_signature(expected, signature, address)
    except ParticipantAuthError as error:
        raise RecurringInsightError("signature_invalid") from error

    if action == "activate":
        if current is not None:
            validate_authorization(current)
            if current["state"] in {"active", "paused"}:
                raise RecurringInsightError("authorization_conflict")
        authorization = {
            "schema": "brainstem.recurring-insight-authorization/v1",
            "userId": user_id,
            "origin": origin,
            "state": "active",
            "revision": 1 if current is None else current["revision"] + 1,
            "binding": challenge["binding"],
            "settings": challenge["settings"],
            "activatedAt": now,
            "pausedAt": None,
            "revokedAt": None,
            "lastRunAt": None,
            "lastSourceAcceptedAt": None,
            "runs": [],
            "lease": None,
        }
    else:
        authorization = dict(current)
        if action == "pause":
            if authorization["state"] != "active":
                raise RecurringInsightError("authorization_not_active")
            authorization["state"] = "paused"
            authorization["pausedAt"] = now
        elif action == "resume":
            if authorization["state"] != "paused":
                raise RecurringInsightError("authorization_not_paused")
            authorization["state"] = "active"
            authorization["pausedAt"] = None
        elif action == "revoke":
            authorization["state"] = "revoked"
            authorization["revokedAt"] = now
        else:
            authorization = {
                "schema": current["schema"],
                "userIdHash": _sha256(current["userId"]),
                "state": "deleted",
                "revision": current["revision"],
                "authorizationSha256": authorization_sha256(current),
                "deletedAt": now,
            }
    consumed = dict(challenge)
    consumed.pop("message")
    consumed.pop("address")
    consumed.pop("nonce")
    consumed["consumedAt"] = now
    return consumed, authorization


def renewal_state(authorization, policy, algorithm_image_digest):
    validate_authorization(authorization)
    if authorization["state"] not in {"active", "paused"}:
        return authorization
    if authorization["binding"] == _binding(policy, algorithm_image_digest):
        return authorization
    result = dict(authorization)
    result["state"] = "renewal_required"
    return result


def recurring_due(
    authorization,
    *,
    validator,
    feature_enabled,
    current_data_consent,
    latest_source_accepted_at,
    new_eligible_recordings,
    now=None,
):
    now = int(time.time() if now is None else now)
    validator(authorization)
    if feature_enabled is not True:
        return False, "feature_disabled"
    if authorization["state"] != "active":
        return False, authorization["state"]
    if current_data_consent is not True:
        return False, "consent_unavailable"
    if not authorization["settings"]["startsAt"] <= now < authorization["settings"]["expiresAt"]:
        return False, "expired"
    if (
        not isinstance(new_eligible_recordings, int)
        or isinstance(new_eligible_recordings, bool)
        or new_eligible_recordings < authorization["settings"]["minimumNewRecordings"]
    ):
        return False, "insufficient_data_change"
    if (
        not isinstance(latest_source_accepted_at, int)
        or isinstance(latest_source_accepted_at, bool)
        or latest_source_accepted_at <= (authorization["lastSourceAcceptedAt"] or 0)
    ):
        return False, "no_new_data"
    cadence = authorization["settings"]["cadenceDays"] * 86400
    if authorization["lastRunAt"] is not None and now - authorization["lastRunAt"] < cadence:
        return False, "cadence"
    recent = [
        timestamp
        for timestamp in authorization["runs"]
        if isinstance(timestamp, int) and now - timestamp < 30 * 86400
    ]
    if len(recent) >= authorization["settings"]["maximumRunsPer30Days"]:
        return False, "budget"
    return True, "due"


def due(
    authorization,
    *,
    feature_enabled,
    current_data_consent,
    latest_source_accepted_at,
    new_eligible_recordings,
    now=None,
):
    return recurring_due(
        authorization,
        validator=validate_authorization,
        feature_enabled=feature_enabled,
        current_data_consent=current_data_consent,
        latest_source_accepted_at=latest_source_accepted_at,
        new_eligible_recordings=new_eligible_recordings,
        now=now,
    )


def claim_recurring_due(
    authorization,
    *,
    validator,
    authorization_hash,
    lease_id,
    feature_enabled,
    current_data_consent,
    latest_source_accepted_at,
    new_eligible_recordings,
    now,
    lease_seconds=300,
):
    eligible, reason = recurring_due(
        authorization,
        validator=validator,
        feature_enabled=feature_enabled,
        current_data_consent=current_data_consent,
        latest_source_accepted_at=latest_source_accepted_at,
        new_eligible_recordings=new_eligible_recordings,
        now=now,
    )
    if not eligible:
        return authorization, None, reason
    if (
        not isinstance(lease_id, str)
        or not SESSION_SECRET.fullmatch(lease_id)
        or not 1 <= lease_seconds <= 600
    ):
        raise RecurringInsightError("lease_invalid")
    current = authorization.get("lease")
    if isinstance(current, dict) and current.get("expiresAt", 0) > now:
        if hmac.compare_digest(
            current.get("tokenSha256", ""), _sha256(lease_id)
        ):
            return authorization, {
                "lease": lease_id,
                "runKey": current["runKey"],
            }, "claimed"
        return authorization, None, "leased"
    run_key = _sha256(
        "{}\0{}".format(
            authorization_hash(authorization), latest_source_accepted_at
        )
    )
    result = dict(authorization)
    result["lease"] = {
        "tokenSha256": _sha256(lease_id),
        "runKey": run_key,
        "sourceAcceptedAt": latest_source_accepted_at,
        "claimedAt": now,
        "expiresAt": now + lease_seconds,
    }
    return result, {"lease": lease_id, "runKey": run_key}, "claimed"


def claim_due(
    authorization,
    *,
    lease_id,
    feature_enabled,
    current_data_consent,
    latest_source_accepted_at,
    new_eligible_recordings,
    now,
    lease_seconds=300,
):
    return claim_recurring_due(
        authorization,
        validator=validate_authorization,
        authorization_hash=authorization_sha256,
        lease_id=lease_id,
        feature_enabled=feature_enabled,
        current_data_consent=current_data_consent,
        latest_source_accepted_at=latest_source_accepted_at,
        new_eligible_recordings=new_eligible_recordings,
        now=now,
        lease_seconds=lease_seconds,
    )


def complete_recurring_lease(
    authorization, lease_id, *, completed_at, validator
):
    validator(authorization)
    lease = authorization.get("lease")
    if (
        authorization["state"] != "active"
        or not isinstance(lease, dict)
        or lease.get("expiresAt", 0) <= completed_at
        or not hmac.compare_digest(lease.get("tokenSha256", ""), _sha256(lease_id))
    ):
        raise RecurringInsightError("lease_unavailable")
    result = dict(authorization)
    result["lastRunAt"] = completed_at
    result["lastSourceAcceptedAt"] = lease["sourceAcceptedAt"]
    result["runs"] = [
        timestamp
        for timestamp in result["runs"]
        if isinstance(timestamp, int) and completed_at - timestamp < 30 * 86400
    ] + [completed_at]
    result["lease"] = None
    return result, dict(lease)


def complete_lease(authorization, lease_id, *, completed_at):
    result, lease = complete_recurring_lease(
        authorization,
        lease_id,
        completed_at=completed_at,
        validator=validate_authorization,
    )
    notification = {
        "schema": "brainstem.recurring-insight-notification/v1",
        "notificationId": _sha256(
            "{}\0{}".format(lease["runKey"], completed_at)
        ),
        "analysisId": result["binding"]["analysisId"],
        "channel": "in_app",
        "message": "Your updated Insight is ready.",
        "createdAt": completed_at,
    }
    return result, notification


def result_expires_at(authorization, completed_at):
    validate_authorization(authorization)
    return completed_at + authorization["settings"]["retentionDays"] * 86400
