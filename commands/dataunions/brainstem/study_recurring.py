"""Participant-owned recurring authority for one exact activated study."""

from copy import deepcopy
import hashlib
import hmac
from itertools import islice
import json
import secrets
import time
import uuid
from urllib.parse import urlparse

from commands.dataunions.brainstem.consent import has_brainstem_data_consent
from commands.dataunions.brainstem.recurring_insight import (
    RecurringInsightError,
    claim_recurring_due,
    complete_recurring_lease,
    recurring_settings,
)
from commands.dataunions.studies.registry import StudyRegistryError, content_sha256
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
SCOPE = "participant:self:study:recurring"
PURPOSE = "brainstem.study-recurring-authorization/v1"
RESOURCE_PREFIX = "urn:brainstem:scope:participant:self:study:recurring:"
ACTIONS = {"activate", "pause", "resume", "revoke", "delete"}
MAX_EVIDENCE = 32
MAX_COMPLETIONS = 32
MAX_OUTBOX = 50
MAX_WORKER_CANDIDATES = 1000
SHA256 = frozenset("0123456789abcdef")


class StudyRecurringError(RuntimeError):
    def __init__(self, code, status_code=400):
        super().__init__(code)
        self.code = code
        self.status_code = status_code


def _sha256(value):
    raw = (
        value.encode("utf-8")
        if isinstance(value, str)
        else json.dumps(value, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    )
    return hashlib.sha256(raw).hexdigest()


def _valid_sha256(value):
    return isinstance(value, str) and len(value) == 64 and set(value) <= SHA256


def _valid_image_digest(value):
    return (
        isinstance(value, str)
        and value.startswith("sha256:")
        and _valid_sha256(value[7:])
    )


def _origin(value):
    parsed = urlparse(value) if isinstance(value, str) else None
    if (
        not parsed
        or parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or parsed.path
        or parsed.query
        or parsed.fragment
    ):
        raise StudyRecurringError("study_recurring_origin_invalid")
    return value


BINDING_FIELDS = {
    "offeringId",
    "proposalId",
    "permitId",
    "permitSha256",
    "operationStateSha256",
    "releaseVersion",
    "releaseSha256",
    "enrollmentSha256",
    "taskPlanSha256",
    "activationProfileSha256",
    "datasetCapability",
    "algorithmId",
    "algorithmVersion",
    "algorithmSourceSha256",
    "algorithmImageDigest",
    "approvedManifestSha256",
    "referenceSha256",
    "resultContractId",
    "resultContractSha256",
    "operationalPolicyId",
    "operationalPolicySha256",
}


def validate_binding(value):
    text_fields = {
        "offeringId",
        "proposalId",
        "permitId",
        "releaseVersion",
        "datasetCapability",
        "algorithmId",
        "algorithmVersion",
        "resultContractId",
        "operationalPolicyId",
    }
    hash_fields = BINDING_FIELDS - text_fields - {"algorithmImageDigest"}
    if (
        not isinstance(value, dict)
        or set(value) != BINDING_FIELDS
        or any(
            not isinstance(value.get(field), str) or not value[field]
            for field in text_fields
        )
        or any(not _valid_sha256(value.get(field)) for field in hash_fields)
        or not _valid_image_digest(value.get("algorithmImageDigest"))
    ):
        raise StudyRecurringError("study_recurring_binding_invalid", 409)
    return value


def authorization_sha256(value):
    return content_sha256(
        {
            key: value.get(key)
            for key in (
                "schema",
                "offeringId",
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


def _authorization_control(value):
    return {
        key: deepcopy(value.get(key))
        for key in (
            "schema",
            "offeringId",
            "state",
            "revision",
            "binding",
            "settings",
            "activatedAt",
            "pausedAt",
            "revokedAt",
        )
    }


def validate_authorization(value):
    if (
        not isinstance(value, dict)
        or set(value)
        != {
            "schema",
            "offeringId",
            "state",
            "revision",
            "binding",
            "settings",
            "activatedAt",
            "pausedAt",
            "revokedAt",
            "lastRunAt",
            "lastSourceAcceptedAt",
            "runs",
            "lease",
            "completions",
            "authorizationSha256",
        }
        or value.get("schema")
        != "brainstem.study-recurring-authorization/v1"
        or value.get("state") not in {"active", "paused", "revoked"}
        or type(value.get("revision")) is not int
        or value["revision"] < 1
        or type(value.get("activatedAt")) is not int
        or value.get("pausedAt") is not None
        and type(value.get("pausedAt")) is not int
        or value.get("revokedAt") is not None
        and type(value.get("revokedAt")) is not int
        or value.get("lastRunAt") is not None
        and type(value.get("lastRunAt")) is not int
        or value.get("lastSourceAcceptedAt") is not None
        and type(value.get("lastSourceAcceptedAt")) is not int
        or not isinstance(value.get("runs"), list)
        or len(value["runs"]) > 31
        or any(type(item) is not int for item in value["runs"])
        or not isinstance(value.get("completions"), list)
        or len(value["completions"]) > MAX_COMPLETIONS
    ):
        raise StudyRecurringError("study_recurring_authorization_invalid", 409)
    validate_binding(value.get("binding"))
    try:
        recurring_settings(value.get("settings"))
    except RecurringInsightError as error:
        raise StudyRecurringError(
            "study_recurring_authorization_invalid", 409
        ) from error
    lease = value.get("lease")
    if lease is not None and (
        not isinstance(lease, dict)
        or set(lease)
        != {
            "tokenSha256",
            "runKey",
            "sourceAcceptedAt",
            "claimedAt",
            "expiresAt",
        }
        or not _valid_sha256(lease.get("tokenSha256"))
        or not _valid_sha256(lease.get("runKey"))
        or type(lease.get("sourceAcceptedAt")) is not int
        or type(lease.get("claimedAt")) is not int
        or type(lease.get("expiresAt")) is not int
        or not lease["claimedAt"] < lease["expiresAt"]
    ):
        raise StudyRecurringError("study_recurring_authorization_invalid", 409)
    for completion in value["completions"]:
        if (
            not isinstance(completion, dict)
            or set(completion)
            != {
                "leaseTokenSha256",
                "runKey",
                "completedAt",
                "notificationQueued",
                "notificationId",
            }
            or not _valid_sha256(completion.get("leaseTokenSha256"))
            or not _valid_sha256(completion.get("runKey"))
            or type(completion.get("completedAt")) is not int
            or type(completion.get("notificationQueued")) is not bool
            or completion["notificationQueued"] is True
            and not _valid_sha256(completion.get("notificationId"))
            or completion["notificationQueued"] is False
            and completion.get("notificationId") is not None
        ):
            raise StudyRecurringError(
                "study_recurring_authorization_invalid", 409
            )
    if value.get("authorizationSha256") != authorization_sha256(value):
        raise StudyRecurringError("study_recurring_authorization_invalid", 409)
    return value


def _message(challenge):
    binding = challenge["binding"]
    settings = challenge["settings"]
    lines = [
        "{} requests a recurring Brainstem study action with your Ethereum account:".format(
            urlparse(challenge["origin"]).netloc
        ),
        challenge["address"],
        "",
        (
            "Allow repeated private study runs only under the exact authority "
            "and limits below. This is separate from enrollment, one-time "
            "Insight approval, notification delivery, and payment."
        ),
        "",
        "URI: {}/participant/studies/{}/recurring".format(
            challenge["origin"], challenge["offeringId"]
        ),
        "Version: 1",
        "Chain ID: {}".format(CHAIN_ID),
        "Nonce: {}".format(challenge["nonce"]),
        "Issued At: {}".format(rfc3339(challenge["issuedAt"])),
        "Expiration Time: {}".format(rfc3339(challenge["expiresAt"])),
        "Request ID: {}".format(challenge["challengeId"]),
        "Purpose: {}".format(PURPOSE),
        "Scope: {}".format(SCOPE),
        "Action: {}".format(challenge["action"]),
        "Offering: {}".format(binding["offeringId"]),
        "Proposal: {}".format(binding["proposalId"]),
        "Permit: {}".format(binding["permitId"]),
        "Permit SHA256: {}".format(binding["permitSha256"]),
        "Operation State SHA256: {}".format(
            binding["operationStateSha256"]
        ),
        "Release Version: {}".format(binding["releaseVersion"]),
        "Release SHA256: {}".format(binding["releaseSha256"]),
        "Enrollment SHA256: {}".format(binding["enrollmentSha256"]),
        "Task Plan SHA256: {}".format(binding["taskPlanSha256"]),
        "Activation Profile SHA256: {}".format(
            binding["activationProfileSha256"]
        ),
        "Dataset Capability: {}".format(binding["datasetCapability"]),
        "Algorithm: {}@{}".format(
            binding["algorithmId"], binding["algorithmVersion"]
        ),
        "Algorithm Source SHA256: {}".format(
            binding["algorithmSourceSha256"]
        ),
        "Algorithm Image Digest: {}".format(
            binding["algorithmImageDigest"]
        ),
        "Approved Manifest SHA256: {}".format(
            binding["approvedManifestSha256"]
        ),
        "Reference SHA256: {}".format(binding["referenceSha256"]),
        "Result Contract: {} {}".format(
            binding["resultContractId"], binding["resultContractSha256"]
        ),
        "Operational Policy: {} {}".format(
            binding["operationalPolicyId"],
            binding["operationalPolicySha256"],
        ),
        "Cadence Days: {}".format(settings["cadenceDays"]),
        "Maximum Runs Per 30 Days: {}".format(
            settings["maximumRunsPer30Days"]
        ),
        "Maximum Charge Minor: 0",
        "Currency: none",
        "Notification: in_app",
        "Retention Days: {}".format(settings["retentionDays"]),
        "Minimum New Recordings: {}".format(
            settings["minimumNewRecordings"]
        ),
        "Starts At: {}".format(rfc3339(settings["startsAt"])),
        "Expires At: {}".format(rfc3339(settings["expiresAt"])),
        "Entitlement: no_charge",
    ]
    if challenge["targetAuthorizationSha256"] is not None:
        lines.append(
            "Target Authorization SHA256: {}".format(
                challenge["targetAuthorizationSha256"]
            )
        )
    lines.extend(
        ["Resources:", "- {}{}".format(RESOURCE_PREFIX, challenge["offeringId"])]
    )
    return "\n".join(lines)


CHALLENGE_FIELDS = {
    "schema",
    "challengeId",
    "userId",
    "address",
    "origin",
    "offeringId",
    "action",
    "binding",
    "settings",
    "targetAuthorizationSha256",
    "nonce",
    "message",
    "issuedAt",
    "expiresAt",
    "consumedAt",
}


def _validate_challenge(
    challenge,
    *,
    user_id,
    address,
    origin,
    current,
    now,
    consumed,
    signature,
):
    target = authorization_sha256(current) if current is not None else None
    if (
        not isinstance(challenge, dict)
        or set(challenge) != CHALLENGE_FIELDS
        or challenge.get("schema") != "brainstem.study-recurring-challenge/v1"
        or challenge.get("userId") != user_id
        or challenge.get("address") != address
        or challenge.get("origin") != origin
        or challenge.get("action") not in ACTIONS
        or challenge.get("offeringId")
        != (current or challenge.get("binding", {})).get("offeringId")
        or challenge.get("targetAuthorizationSha256") != target
        or not isinstance(challenge.get("challengeId"), str)
        or not IDENTIFIER.fullmatch(challenge["challengeId"])
        or not isinstance(challenge.get("nonce"), str)
        or not SESSION_SECRET.fullmatch(challenge["nonce"])
        or type(challenge.get("issuedAt")) is not int
        or type(challenge.get("expiresAt")) is not int
        or challenge["expiresAt"] - challenge["issuedAt"] != CHALLENGE_TTL
    ):
        raise StudyRecurringError("study_recurring_challenge_unavailable", 401)
    validate_binding(challenge.get("binding"))
    try:
        recurring_settings(challenge.get("settings"))
    except RecurringInsightError as error:
        raise StudyRecurringError(
            "study_recurring_challenge_unavailable", 401
        ) from error
    if consumed:
        if (
            type(challenge.get("consumedAt")) is not int
            or challenge["consumedAt"] < challenge["issuedAt"]
            or challenge["consumedAt"] >= challenge["expiresAt"]
        ):
            raise StudyRecurringError(
                "study_recurring_challenge_unavailable", 401
            )
    elif (
        challenge.get("consumedAt") is not None
        or challenge["issuedAt"] > now
        or challenge["expiresAt"] <= now
    ):
        raise StudyRecurringError("study_recurring_challenge_unavailable", 401)
    expected = _message(challenge)
    if not hmac.compare_digest(challenge.get("message", ""), expected):
        raise StudyRecurringError("study_recurring_challenge_unavailable", 401)
    try:
        verify_wallet_signature(expected, signature, address)
    except ParticipantAuthError as error:
        raise StudyRecurringError("study_recurring_signature_invalid", 401) from error
    return challenge


def _next_authorization(current, challenge, now):
    action = challenge["action"]
    if action == "activate":
        if (
            current is not None
            and current["state"] in {"active", "paused"}
            and current["binding"] == challenge["binding"]
        ):
            raise StudyRecurringError("study_recurring_authorization_conflict", 409)
        result = {
            "schema": "brainstem.study-recurring-authorization/v1",
            "offeringId": challenge["offeringId"],
            "state": "active",
            "revision": 1 if current is None else current["revision"] + 1,
            "binding": deepcopy(challenge["binding"]),
            "settings": deepcopy(challenge["settings"]),
            "activatedAt": now,
            "pausedAt": None,
            "revokedAt": None,
            "lastRunAt": None,
            "lastSourceAcceptedAt": None,
            "runs": [],
            "lease": None,
            "completions": [],
            "authorizationSha256": None,
        }
    else:
        if current is None:
            raise StudyRecurringError("study_recurring_authorization_unavailable", 409)
        result = deepcopy(current)
        if action == "pause":
            if result["state"] != "active":
                raise StudyRecurringError("study_recurring_authorization_not_active", 409)
            result["state"] = "paused"
            result["pausedAt"] = now
            result["lease"] = None
        elif action == "resume":
            if result["state"] != "paused":
                raise StudyRecurringError("study_recurring_authorization_not_paused", 409)
            result["state"] = "active"
            result["pausedAt"] = None
        elif action == "revoke":
            result["state"] = "revoked"
            result["revokedAt"] = now
            result["lease"] = None
        else:
            return None
    result["authorizationSha256"] = authorization_sha256(result)
    return result


def replay_evidence(evidence, *, user_id, address, origin):
    if not isinstance(evidence, list) or not 1 <= len(evidence) <= MAX_EVIDENCE:
        raise StudyRecurringError("study_recurring_evidence_invalid", 409)
    current = None
    for item in evidence:
        if (
            not isinstance(item, dict)
            or set(item) != {"schema", "challenge", "signature", "signatureSha256"}
            or item.get("schema") != "brainstem.study-recurring-evidence/v1"
            or not isinstance(item.get("signature"), str)
            or item.get("signatureSha256") != _sha256(item["signature"])
        ):
            raise StudyRecurringError("study_recurring_evidence_invalid", 409)
        try:
            challenge = _validate_challenge(
                item.get("challenge"),
                user_id=user_id,
                address=address,
                origin=origin,
                current=current,
                now=None,
                consumed=True,
                signature=item["signature"],
            )
        except StudyRecurringError as error:
            raise StudyRecurringError(
                "study_recurring_evidence_invalid", 409
            ) from error
        if challenge["action"] == "delete":
            raise StudyRecurringError("study_recurring_evidence_invalid", 409)
        current = _next_authorization(current, challenge, challenge["consumedAt"])
    return current


def _projection(authorization, state_override=None):
    if authorization is None:
        return {
            "schema": "brainstem.study-recurring-status/v1",
            "state": "not_authorized",
            "revision": None,
            "binding": None,
            "settings": None,
            "activatedAt": None,
            "pausedAt": None,
            "revokedAt": None,
            "lastRunAt": None,
        }
    validate_authorization(authorization)
    return {
        "schema": "brainstem.study-recurring-status/v1",
        "state": state_override or authorization["state"],
        "revision": authorization["revision"],
        "binding": deepcopy(authorization["binding"]),
        "settings": deepcopy(authorization["settings"]),
        "activatedAt": authorization["activatedAt"],
        "pausedAt": authorization["pausedAt"],
        "revokedAt": authorization["revokedAt"],
        "lastRunAt": authorization["lastRunAt"],
    }


def block_recurring_for_renewal(private):
    if not isinstance(private, dict):
        return
    authorization = private.get("recurringAuthorization")
    if isinstance(authorization, dict) and authorization.get("state") in {
        "active",
        "paused",
    }:
        authorization = deepcopy(authorization)
        authorization["lease"] = None
        private["recurringAuthorization"] = authorization
    private.pop("recurringChallenge", None)
    private.pop("recurringOutbox", None)


def scrub_recurring(private, *, state, now):
    del now
    if not isinstance(private, dict):
        return
    authorization = private.get("recurringAuthorization")
    tombstone = private.get("recurringTombstone")
    revision = (
        authorization.get("revision")
        if isinstance(authorization, dict)
        and type(authorization.get("revision")) is int
        else tombstone.get("revision")
        if isinstance(tombstone, dict)
        and type(tombstone.get("revision")) is int
        else None
    )
    for key in (
        "recurringChallenge",
        "recurringEvidence",
        "recurringAuthorization",
        "recurringOutbox",
        "recurringTombstone",
    ):
        private.pop(key, None)
    if revision is not None:
        private["recurringTombstone"] = {
            "schema": "brainstem.study-recurring-tombstone/v1",
            "state": state,
            "revision": revision,
        }


class StudyRecurringService:
    def __init__(
        self,
        auth,
        users_dao,
        study_dao,
        enrollment_service,
        operations_service,
        registry,
        *,
        feature_enabled,
        clock=time.time,
        id_factory=lambda: uuid.uuid4().hex,
        nonce_factory=lambda: secrets.token_urlsafe(32),
        lease_factory=lambda: secrets.token_urlsafe(32),
    ):
        self.auth = auth
        self.users_dao = users_dao
        self.study_dao = study_dao
        self.enrollment_service = enrollment_service
        self.operations_service = operations_service
        self.registry = registry
        self.feature_enabled = feature_enabled
        self.clock = clock
        self.id_factory = id_factory
        self.nonce_factory = nonce_factory
        self.lease_factory = lease_factory

    def _enabled(self):
        if self.feature_enabled is not True:
            raise StudyRecurringError("study_recurring_disabled", 503)

    def _participant(self, token, origin):
        self._enabled()
        origin = _origin(origin)
        try:
            _session_id, _session, user = self.auth.authenticate(token, origin)
            address = checksum_address(user["public_address"])
        except (KeyError, ParticipantAuthError) as error:
            raise StudyRecurringError("study_recurring_participant_invalid", 401) from error
        return user, address, origin

    @staticmethod
    def _private(state, offering_id):
        offerings = state.get("offerings") if isinstance(state, dict) else None
        private = offerings.get(offering_id) if isinstance(offerings, dict) else None
        return private if isinstance(private, dict) else {}

    def _current_context(
        self,
        user_id,
        offering_id,
        state,
        capabilities=("lease", "reminder"),
    ):
        self._enabled()
        try:
            user = self.users_dao.get_doc_by_id(user_id)
        except Exception as error:
            raise StudyRecurringError("study_recurring_user_source_unavailable", 503) from error
        if not isinstance(user, dict) or user.get("_id") != user_id:
            raise StudyRecurringError("study_recurring_user_source_invalid", 503)
        try:
            address = checksum_address(user.get("public_address"))
        except ParticipantAuthError as error:
            raise StudyRecurringError("study_recurring_identity_changed", 409) from error
        if user.get("is_access_blocked") is True or not has_brainstem_data_consent(user):
            raise StudyRecurringError("consent_unavailable", 409)
        private = self._private(state, offering_id)
        enrollment = private.get("enrollment")
        if not isinstance(enrollment, dict) or enrollment.get("state") != "active":
            reason = (
                enrollment.get("state")
                if isinstance(enrollment, dict)
                else "enrollment_unavailable"
            )
            raise StudyRecurringError(reason, 409)
        try:
            enrollment = self.enrollment_service.load_verified_enrollment(
                user_id, offering_id, state=state, user=user
            )
            if self.operations_service.enrollment_requires_renewal(enrollment):
                raise StudyRecurringError("renewal_required", 409)
            status = self.operations_service.load_verified_status(
                enrollment["proposalId"], enrollment["permitId"]
            )
            operation_state = status["state"]
            release = self.registry.release(
                offering_id,
                enrollment["releaseVersion"],
                enrollment["releaseSha256"],
            )
            profile = self.registry.activation_profile(
                offering_id,
                release["releaseVersion"],
                release["releaseSha256"],
            )
            values = profile["content"]
            if (
                operation_state["proposalId"] != enrollment["proposalId"]
                or operation_state["permitId"] != enrollment["permitId"]
                or operation_state["releaseVersion"] != enrollment["releaseVersion"]
                or operation_state["releaseSha256"] != enrollment["releaseSha256"]
                or operation_state["taskPlan"] != enrollment["taskPlan"]
                or operation_state["lifecycleState"] != "active"
                or operation_state["disposition"] != "current"
                or release["taskPlan"] != enrollment["taskPlan"]
                or release["activationProfile"]["sha256"] != profile["sha256"]
                or values["environment"] != "generated-local"
                or values["dataMode"] != "generated_only"
                or values["algorithmNetwork"] != "none"
                or values["payment"] != {"currency": "none", "amountMinor": 0}
            ):
                raise StudyRecurringError("study_recurring_authority_unavailable", 409)
            if any(
                self.operations_service.operation_allowed(
                    enrollment["proposalId"], enrollment["permitId"], capability
                )
                is not True
                for capability in capabilities
            ):
                raise StudyRecurringError(
                    "study_recurring_authority_unavailable", 409
                )
            fenced_status = self.operations_service.load_verified_status(
                enrollment["proposalId"], enrollment["permitId"]
            )
            fenced_state = fenced_status["state"]
            if (
                fenced_state.get("stateSha256")
                != operation_state["stateSha256"]
                or fenced_state != operation_state
            ):
                raise StudyRecurringError(
                    "study_recurring_authority_changed", 409
                )
            operation_state = fenced_state
        except StudyRecurringError:
            raise
        except (KeyError, StudyRegistryError) as error:
            raise StudyRecurringError("study_recurring_authority_unavailable", 409) from error
        except Exception as error:
            status_code = getattr(error, "status_code", 503)
            raise StudyRecurringError(
                "study_recurring_authority_unavailable",
                503 if status_code >= 500 else 409,
            ) from error
        binding = {
            "offeringId": offering_id,
            "proposalId": enrollment["proposalId"],
            "permitId": enrollment["permitId"],
            "permitSha256": operation_state["permitSha256"],
            "operationStateSha256": operation_state["stateSha256"],
            "releaseVersion": release["releaseVersion"],
            "releaseSha256": release["releaseSha256"],
            "enrollmentSha256": enrollment["enrollmentSha256"],
            "taskPlanSha256": release["taskPlan"]["sha256"],
            "activationProfileSha256": profile["sha256"],
            "datasetCapability": values["datasetCapability"],
            "algorithmId": values["algorithmId"],
            "algorithmVersion": values["algorithmVersion"],
            "algorithmSourceSha256": values["algorithmSourceSha256"],
            "algorithmImageDigest": values["algorithmImageDigest"],
            "approvedManifestSha256": values["approvedManifestSha256"],
            "referenceSha256": values["referenceSha256"],
            "resultContractId": values["resultContractId"],
            "resultContractSha256": values["resultContractSha256"],
            "operationalPolicyId": values["operationalPolicyId"],
            "operationalPolicySha256": values["operationalPolicySha256"],
        }
        validate_binding(binding)
        return {"user": user, "address": address, "binding": binding}

    def _load_authorization(self, state, offering_id, user_id, address, origin):
        private = self._private(state, offering_id)
        authorization = private.get("recurringAuthorization")
        evidence = private.get("recurringEvidence")
        if authorization is None:
            if evidence not in (None, []):
                raise StudyRecurringError("study_recurring_evidence_invalid", 409)
            return None
        validate_authorization(authorization)
        if (
            authorization["offeringId"] != offering_id
            or authorization["binding"]["offeringId"] != offering_id
        ):
            raise StudyRecurringError(
                "study_recurring_authorization_invalid", 409
            )
        replayed = replay_evidence(
            evidence, user_id=user_id, address=address, origin=origin
        )
        if _authorization_control(replayed) != _authorization_control(authorization):
            raise StudyRecurringError("study_recurring_evidence_invalid", 409)
        return authorization

    def status(self, token, origin, offering_id):
        user, address, origin = self._participant(token, origin)
        state = self.study_dao.get_state(user["_id"]) or {}
        authorization = self._load_authorization(
            state, offering_id, user["_id"], address, origin
        )
        tombstone = self._private(state, offering_id).get("recurringTombstone")
        if authorization is None and isinstance(tombstone, dict):
            if (
                set(tombstone) != {"schema", "state", "revision"}
                or tombstone.get("schema")
                != "brainstem.study-recurring-tombstone/v1"
                or tombstone.get("state") not in {"revoked", "deleted"}
                or type(tombstone.get("revision")) is not int
            ):
                raise StudyRecurringError("study_recurring_authorization_invalid", 409)
            result = _projection(None)
            result["state"] = tombstone["state"]
            result["revision"] = tombstone["revision"]
            return result
        override = None
        if authorization is not None and authorization["state"] in {"active", "paused"}:
            try:
                context = self._current_context(user["_id"], offering_id, state)
                if context["binding"] != authorization["binding"]:
                    override = "renewal_required"
            except StudyRecurringError as error:
                if error.status_code >= 500:
                    raise
                override = error.code
        return _projection(authorization, override)

    def challenge(self, token, origin, offering_id, action, settings=None):
        user, address, origin = self._participant(token, origin)
        now = int(self.clock())
        if action not in ACTIONS:
            raise StudyRecurringError("study_recurring_action_invalid")
        state = self.study_dao.get_state(user["_id"]) or {}
        current = self._load_authorization(
            state, offering_id, user["_id"], address, origin
        )
        evidence = self._private(state, offering_id).get(
            "recurringEvidence", []
        )
        if action != "delete" and (
            not isinstance(evidence, list)
            or len(evidence)
            >= (MAX_EVIDENCE if action == "revoke" else MAX_EVIDENCE - 1)
        ):
            raise StudyRecurringError("study_recurring_evidence_limit", 409)
        if action == "activate":
            try:
                settings = recurring_settings(settings)
            except RecurringInsightError as error:
                raise StudyRecurringError("study_recurring_settings_invalid") from error
            context = self._current_context(user["_id"], offering_id, state)
            binding = context["binding"]
        else:
            if settings is not None or current is None:
                raise StudyRecurringError("study_recurring_action_invalid")
            binding = current["binding"]
            settings = current["settings"]
        challenge_id = self.id_factory()
        nonce = self.nonce_factory()
        if not IDENTIFIER.fullmatch(challenge_id or "") or not SESSION_SECRET.fullmatch(
            nonce or ""
        ):
            raise RuntimeError("invalid generated recurring study challenge")
        challenge = {
            "schema": "brainstem.study-recurring-challenge/v1",
            "challengeId": challenge_id,
            "userId": user["_id"],
            "address": address,
            "origin": origin,
            "offeringId": offering_id,
            "action": action,
            "binding": deepcopy(binding),
            "settings": deepcopy(settings),
            "targetAuthorizationSha256": (
                authorization_sha256(current) if current is not None else None
            ),
            "nonce": nonce,
            "message": None,
            "issuedAt": now,
            "expiresAt": now + CHALLENGE_TTL,
            "consumedAt": None,
        }
        challenge["message"] = _message(challenge)

        def store(value):
            private = value.setdefault("offerings", {}).setdefault(offering_id, {})
            latest = self._load_authorization(
                value, offering_id, user["_id"], address, origin
            )
            if (
                authorization_sha256(latest) if latest is not None else None
            ) != challenge["targetAuthorizationSha256"]:
                raise StudyRecurringError("study_recurring_authorization_changed", 409)
            private["recurringChallenge"] = deepcopy(challenge)
            return value

        self.study_dao.mutate_state(user["_id"], store)
        return {
            "schema": "brainstem.study-recurring-signature-request/v1",
            "challengeId": challenge_id,
            "message": challenge["message"],
            "expiresAt": challenge["expiresAt"],
            "chainId": CHAIN_ID,
            "method": "personal_sign",
        }

    def apply(self, token, origin, offering_id, challenge_id, signature):
        user, address, origin = self._participant(token, origin)
        now = int(self.clock())

        def apply_action(value):
            private = value.setdefault("offerings", {}).setdefault(offering_id, {})
            current = self._load_authorization(
                value, offering_id, user["_id"], address, origin
            )
            challenge = private.get("recurringChallenge")
            if not isinstance(challenge, dict) or challenge.get("challengeId") != challenge_id:
                raise StudyRecurringError("study_recurring_challenge_unavailable", 401)
            _validate_challenge(
                challenge,
                user_id=user["_id"],
                address=address,
                origin=origin,
                current=current,
                now=now,
                consumed=False,
                signature=signature,
            )
            if challenge["action"] == "activate":
                context = self._current_context(
                    user["_id"], offering_id, value
                )
                if context["binding"] != challenge["binding"]:
                    raise StudyRecurringError(
                        "study_recurring_authorization_changed", 409
                    )
            consumed = deepcopy(challenge)
            consumed["consumedAt"] = now
            if challenge["action"] == "delete":
                scrub_recurring(private, state="deleted", now=now)
                return value
            evidence = private.setdefault("recurringEvidence", [])
            if (
                not isinstance(evidence, list)
                or len(evidence)
                >= (
                    MAX_EVIDENCE
                    if challenge["action"] == "revoke"
                    else MAX_EVIDENCE - 1
                )
            ):
                raise StudyRecurringError("study_recurring_evidence_limit", 409)
            evidence.append(
                {
                    "schema": "brainstem.study-recurring-evidence/v1",
                    "challenge": consumed,
                    "signature": signature,
                    "signatureSha256": _sha256(signature),
                }
            )
            authorization = _next_authorization(current, consumed, now)
            private["recurringAuthorization"] = authorization
            if challenge["action"] == "activate":
                private.pop("recurringOutbox", None)
            private.pop("recurringChallenge", None)
            private.pop("recurringTombstone", None)
            return value

        state = self.study_dao.mutate_state(user["_id"], apply_action)
        private = self._private(state, offering_id)
        authorization = private.get("recurringAuthorization")
        if authorization is None and isinstance(private.get("recurringTombstone"), dict):
            result = _projection(None)
            result["state"] = private["recurringTombstone"]["state"]
            result["revision"] = private["recurringTombstone"]["revision"]
            return result
        return _projection(authorization)

    def claim(
        self,
        user_id,
        offering_id,
        *,
        latest_source_accepted_at,
        new_eligible_recordings,
        lease_id=None,
        now=None,
    ):
        self._enabled()
        now = int(self.clock() if now is None else now)
        lease_id = lease_id or self.lease_factory()
        state = self.study_dao.get_state(user_id) or {}
        try:
            context = self._current_context(user_id, offering_id, state)
        except StudyRecurringError as error:
            if error.status_code >= 500:
                raise
            return {"status": "not_due", "reason": error.code, "capability": None}
        origin = self._evidence_origin(state, offering_id)

        outcome = {}

        def claim_current(value):
            latest_context = self._current_context(user_id, offering_id, value)
            authorization = self._load_authorization(
                value,
                offering_id,
                user_id,
                latest_context["address"],
                origin,
            )
            if (
                authorization is None
                or authorization["binding"] != latest_context["binding"]
            ):
                outcome.update(status="not_due", reason="renewal_required", capability=None)
                return value
            outbox = self._validated_outbox(value, offering_id)
            if len(outbox) >= MAX_OUTBOX:
                authorization = deepcopy(authorization)
                authorization["lease"] = None
                self._private(value, offering_id)[
                    "recurringAuthorization"
                ] = authorization
                outcome.update(
                    status="not_due",
                    reason="outbox_full",
                    capability=None,
                )
                return value
            try:
                updated, capability, reason = claim_recurring_due(
                    authorization,
                    validator=validate_authorization,
                    authorization_hash=authorization_sha256,
                    lease_id=lease_id,
                    feature_enabled=self.feature_enabled,
                    current_data_consent=True,
                    latest_source_accepted_at=latest_source_accepted_at,
                    new_eligible_recordings=new_eligible_recordings,
                    now=now,
                )
            except RecurringInsightError as error:
                raise StudyRecurringError(str(error), 409) from error
            if updated is not authorization:
                self._private(value, offering_id)["recurringAuthorization"] = updated
            outcome.update(
                status="claimed" if capability else "not_due",
                reason=reason,
                capability=capability,
            )
            return value

        self.study_dao.mutate_state(user_id, claim_current)
        return outcome

    def _evidence_origin(self, state, offering_id):
        evidence = self._private(state, offering_id).get("recurringEvidence")
        try:
            return evidence[0]["challenge"]["origin"]
        except (KeyError, IndexError, TypeError) as error:
            raise StudyRecurringError("study_recurring_evidence_invalid", 409) from error

    def revalidate_claim(self, user_id, offering_id, lease_id, run_key):
        state = self.study_dao.get_state(user_id) or {}
        context = self._current_context(user_id, offering_id, state)
        origin = self._evidence_origin(state, offering_id)
        authorization = self._load_authorization(
            state, offering_id, user_id, context["address"], origin
        )
        outbox = self._validated_outbox(state, offering_id)
        lease = (authorization or {}).get("lease")
        if (
            authorization is None
            or authorization["binding"] != context["binding"]
            or authorization["state"] != "active"
            or len(outbox) >= MAX_OUTBOX
            or not isinstance(lease, dict)
            or lease.get("expiresAt", 0) <= int(self.clock())
            or lease.get("runKey") != run_key
            or not hmac.compare_digest(
                lease.get("tokenSha256", ""), _sha256(lease_id)
            )
        ):
            raise StudyRecurringError("study_recurring_lease_unavailable", 409)
        return True

    def discard_claim(self, user_id, offering_id, lease_id):
        token_sha256 = _sha256(lease_id)

        def discard(value):
            authorization = self._private(value, offering_id).get(
                "recurringAuthorization"
            )
            if isinstance(authorization, dict):
                lease = authorization.get("lease")
                if isinstance(lease, dict) and hmac.compare_digest(
                    lease.get("tokenSha256", ""), token_sha256
                ):
                    authorization = deepcopy(authorization)
                    authorization["lease"] = None
                    self._private(value, offering_id)[
                        "recurringAuthorization"
                    ] = authorization
            return value

        self.study_dao.mutate_state(user_id, discard)

    def complete(self, user_id, offering_id, lease_id, run_key, *, completed_at=None):
        self._enabled()
        completed_at = int(self.clock() if completed_at is None else completed_at)
        state = self.study_dao.get_state(user_id) or {}
        context = self._current_context(
            user_id, offering_id, state, capabilities=("lease", "reminder")
        )
        origin = self._evidence_origin(state, offering_id)
        result = {}
        token_sha256 = _sha256(lease_id)

        def finish(value):
            latest_context = self._current_context(
                user_id,
                offering_id,
                value,
                capabilities=("lease", "reminder"),
            )
            authorization = self._load_authorization(
                value,
                offering_id,
                user_id,
                latest_context["address"],
                origin,
            )
            if (
                authorization is None
                or authorization["binding"] != latest_context["binding"]
            ):
                raise StudyRecurringError("study_recurring_authorization_changed", 409)
            for completion in authorization["completions"]:
                if hmac.compare_digest(
                    completion["leaseTokenSha256"], token_sha256
                ):
                    if completion["runKey"] != run_key:
                        raise StudyRecurringError("study_recurring_completion_conflict", 409)
                    result.update(completion)
                    return value
            try:
                updated, lease = complete_recurring_lease(
                    authorization,
                    lease_id,
                    completed_at=completed_at,
                    validator=validate_authorization,
                )
            except RecurringInsightError as error:
                raise StudyRecurringError("study_recurring_lease_unavailable", 409) from error
            if lease["runKey"] != run_key:
                raise StudyRecurringError("study_recurring_completion_conflict", 409)
            notification_id = _sha256(
                "brainstem.study-recurring.outbox/v1\0{}".format(run_key)
            )
            private = self._private(value, offering_id)
            outbox = private.get("recurringOutbox", [])
            notification_queued = False
            if isinstance(outbox, list) and len(outbox) <= MAX_OUTBOX:
                try:
                    for item in outbox:
                        self._notification(item)
                except StudyRecurringError:
                    pass
                else:
                    if any(
                        item["notificationId"] == notification_id
                        for item in outbox
                    ):
                        notification_queued = True
                    elif len(outbox) < MAX_OUTBOX:
                        private["recurringOutbox"] = outbox + [
                            {
                                "schema": (
                                    "brainstem.study-recurring-notification/v1"
                                ),
                                "notificationId": notification_id,
                                "messageKey": "study_result_ready",
                                "state": "unread",
                                "createdAt": completed_at,
                                "readAt": None,
                            }
                        ]
                        notification_queued = True
            completion = {
                "leaseTokenSha256": token_sha256,
                "runKey": run_key,
                "completedAt": completed_at,
                "notificationQueued": notification_queued,
                "notificationId": (
                    notification_id if notification_queued else None
                ),
            }
            updated["completions"] = (
                updated["completions"] + [completion]
            )[-MAX_COMPLETIONS:]
            private["recurringAuthorization"] = updated
            result.update(completion)
            return value

        self.study_dao.mutate_state(user_id, finish)
        return {
            "schema": "brainstem.study-recurring-completion/v1",
            "status": "completed",
            "notificationQueued": result["notificationQueued"],
            "notificationId": result["notificationId"],
            "completedAt": result["completedAt"],
        }

    @staticmethod
    def _notification(item):
        if (
            not isinstance(item, dict)
            or set(item)
            != {
                "schema",
                "notificationId",
                "messageKey",
                "state",
                "createdAt",
                "readAt",
            }
            or item.get("schema")
            != "brainstem.study-recurring-notification/v1"
            or not _valid_sha256(item.get("notificationId"))
            or item.get("messageKey") != "study_result_ready"
            or item.get("state") not in {"unread", "read"}
            or type(item.get("createdAt")) is not int
            or item.get("readAt") is not None
            and type(item.get("readAt")) is not int
        ):
            raise StudyRecurringError("study_recurring_outbox_invalid", 409)
        return deepcopy(item)

    def _validated_outbox(self, state, offering_id):
        outbox = self._private(state, offering_id).get(
            "recurringOutbox", []
        )
        if not isinstance(outbox, list) or len(outbox) > MAX_OUTBOX:
            raise StudyRecurringError("study_recurring_outbox_invalid", 409)
        for item in outbox:
            self._notification(item)
        return outbox

    def _require_outbox_authority(
        self, user_id, offering_id, state, address, origin
    ):
        context = self._current_context(user_id, offering_id, state)
        if context["address"] != address:
            raise StudyRecurringError("study_recurring_identity_changed", 409)
        authorization = self._load_authorization(
            state,
            offering_id,
            user_id,
            context["address"],
            origin,
        )
        if (
            authorization is None
            or authorization["state"] != "active"
            or authorization["binding"] != context["binding"]
        ):
            raise StudyRecurringError(
                "study_recurring_outbox_authority_unavailable", 409
            )
        return authorization

    def _suppress_unread_in_state(self, state, offering_id):
        private = self._private(state, offering_id)
        outbox = private.get("recurringOutbox")
        if not isinstance(outbox, list):
            private.pop("recurringOutbox", None)
            return state
        retained = []
        for item in outbox:
            try:
                notification = self._notification(item)
            except StudyRecurringError:
                continue
            if notification["state"] == "read":
                retained.append(notification)
        if retained:
            private["recurringOutbox"] = retained
        else:
            private.pop("recurringOutbox", None)
        return state

    def _suppress_unread(self, user_id, offering_id):
        self.study_dao.mutate_state(
            user_id,
            lambda state: self._suppress_unread_in_state(
                state, offering_id
            ),
        )

    def list_outbox(self, token, origin, offering_id):
        user, address, origin = self._participant(token, origin)
        state = self.study_dao.get_state(user["_id"]) or {}
        try:
            self._require_outbox_authority(
                user["_id"], offering_id, state, address, origin
            )
        except StudyRecurringError as error:
            if error.status_code < 500:
                self._suppress_unread(user["_id"], offering_id)
            raise
        outbox = self._validated_outbox(state, offering_id)
        return {
            "schema": "brainstem.study-recurring-outbox/v1",
            "items": [self._notification(item) for item in reversed(outbox)],
        }

    def acknowledge(self, token, origin, offering_id, notification_id):
        user, address, origin = self._participant(token, origin)
        if not _valid_sha256(notification_id):
            raise StudyRecurringError("study_recurring_notification_not_found", 404)
        result = {}
        denied = {}

        def read(value):
            result.clear()
            denied.clear()
            try:
                self._require_outbox_authority(
                    user["_id"], offering_id, value, address, origin
                )
            except StudyRecurringError as error:
                if error.status_code >= 500:
                    raise
                denied["error"] = error
                return self._suppress_unread_in_state(value, offering_id)
            outbox = self._validated_outbox(value, offering_id)
            for index, item in enumerate(outbox):
                current = self._notification(item)
                if current["notificationId"] == notification_id:
                    if current["state"] == "unread":
                        current["state"] = "read"
                        current["readAt"] = int(self.clock())
                        outbox[index] = current
                    result.update(current)
                    return value
            raise StudyRecurringError("study_recurring_notification_not_found", 404)

        self.study_dao.mutate_state(user["_id"], read)
        if denied:
            raise denied["error"]
        return result

    def delete_notification(self, token, origin, offering_id, notification_id):
        user, _address, _origin_value = self._participant(token, origin)
        if not _valid_sha256(notification_id):
            raise StudyRecurringError("study_recurring_notification_not_found", 404)

        def delete(value):
            private = self._private(value, offering_id)
            outbox = private.get("recurringOutbox", [])
            if not isinstance(outbox, list):
                private.pop("recurringOutbox", None)
                return value
            retained = [
                item
                for item in outbox
                if not isinstance(item, dict)
                or item.get("notificationId") != notification_id
            ]
            if retained:
                private["recurringOutbox"] = retained
            else:
                private.pop("recurringOutbox", None)
            return value

        self.study_dao.mutate_state(user["_id"], delete)


class GeneratedStudyRecurringWorker:
    """One generated local tick; scheduling and external delivery stay out of scope."""

    def __init__(
        self,
        service,
        candidate_source,
        new_data_source,
        callback,
        *,
        recurring_enabled,
        generated_worker_enabled,
        external_delivery_enabled,
    ):
        self.service = service
        self.candidate_source = candidate_source
        self.new_data_source = new_data_source
        self.callback = callback
        self.recurring_enabled = recurring_enabled
        self.generated_worker_enabled = generated_worker_enabled
        self.external_delivery_enabled = external_delivery_enabled

    def tick(self, offering_id):
        if (
            self.recurring_enabled is not True
            or self.generated_worker_enabled is not True
            or self.external_delivery_enabled is not False
            or not callable(self.candidate_source)
            or not callable(self.new_data_source)
            or not callable(self.callback)
        ):
            raise StudyRecurringError("study_recurring_worker_disabled", 503)
        candidate_source = self.candidate_source()
        if isinstance(candidate_source, (str, bytes, dict)):
            raise StudyRecurringError("study_recurring_candidates_invalid", 503)
        try:
            candidates = list(
                islice(iter(candidate_source), MAX_WORKER_CANDIDATES + 1)
            )
        except TypeError as error:
            raise StudyRecurringError(
                "study_recurring_candidates_invalid", 503
            ) from error
        if (
            len(candidates) > MAX_WORKER_CANDIDATES
            or any(not isinstance(item, str) or not item for item in candidates)
            or len(set(candidates)) != len(candidates)
        ):
            raise StudyRecurringError("study_recurring_candidates_invalid", 503)
        claimed = 0
        completed = 0
        skipped = 0
        inspected = 0
        for user_id in candidates:
            inspected += 1
            facts = self.new_data_source(user_id, offering_id)
            if (
                not isinstance(facts, dict)
                or set(facts)
                != {"latestSourceAcceptedAt", "newEligibleRecordings"}
                or type(facts["latestSourceAcceptedAt"]) is not int
                or type(facts["newEligibleRecordings"]) is not int
                or facts["newEligibleRecordings"] < 0
            ):
                raise StudyRecurringError("study_recurring_facts_invalid", 503)
            outcome = self.service.claim(
                user_id,
                offering_id,
                latest_source_accepted_at=facts["latestSourceAcceptedAt"],
                new_eligible_recordings=facts["newEligibleRecordings"],
            )
            capability = outcome.get("capability")
            if not isinstance(capability, dict):
                skipped += 1
                continue
            claimed += 1
            try:
                self.service.revalidate_claim(
                    user_id,
                    offering_id,
                    capability["lease"],
                    capability["runKey"],
                )
            except StudyRecurringError as error:
                self.service.discard_claim(
                    user_id, offering_id, capability["lease"]
                )
                if error.status_code >= 500:
                    raise
                skipped += 1
                break
            self.callback(user_id, offering_id, deepcopy(capability))
            self.service.complete(
                user_id,
                offering_id,
                capability["lease"],
                capability["runKey"],
            )
            completed += 1
            break
        return {
            "schema": "brainstem.study-recurring-generated-tick/v1",
            "inspectedCount": inspected,
            "claimedCount": claimed,
            "completedCount": completed,
            "skippedCount": skipped,
        }
