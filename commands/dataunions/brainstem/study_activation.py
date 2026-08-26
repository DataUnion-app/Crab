"""Operator-signed immutable study permits with no lifecycle side effects."""

from copy import deepcopy
import hashlib
import hmac
import re
import secrets
import time
import uuid
from urllib.parse import urlparse

from commands.dataunions.brainstem.study_proposals import (
    REVIEW_DOMAINS,
    SHA256,
    StudyProposalConflict,
    StudyProposalError,
    normalize_proposal_id,
    validate_stored_proposal,
)
from commands.dataunions.studies.registry import StudyRegistryError, content_sha256
from commands.users.participant_auth import (
    ParticipantAuthError,
    checksum_address,
    rfc3339,
    validate_origin,
    verify_wallet_signature,
)
from dao.study_activation_dao import StudyActivationStateError


CHALLENGE_ID = re.compile(r"^[0-9a-f]{32}$")
PERMIT_ID = re.compile(r"^permit_[0-9a-f]{32}$")
NONCE = re.compile(r"^[A-Za-z0-9_-]{16,128}$")
PURPOSE = "brainstem.study.operator-permit"
MAX_CHALLENGE_TTL = 600


class StudyActivationError(Exception):
    def __init__(self, message, status_code=400):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _text_sha256(value):
    if not isinstance(value, str):
        raise StudyActivationError("study_activation_evidence_invalid", 409)
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _wallet(value, message="study_operator_invalid"):
    try:
        return checksum_address(value).lower()
    except ParticipantAuthError as error:
        raise StudyActivationError(message, 403) from error


def _strict_origin(value, allowed_origins):
    try:
        return validate_origin(value, allowed_origins)
    except ParticipantAuthError as error:
        raise StudyActivationError("study_operator_origin_forbidden", 403) from error


def _current_revision(proposal):
    revision = proposal["revisions"][-1]
    if (
        proposal.get("currentRevisionId") != revision["revisionId"]
        or proposal.get("currentRevisionSha256") != revision["revisionSha256"]
    ):
        raise StudyProposalConflict("The study proposal changed concurrently")
    return revision


def _approved_decisions(proposal, revision, operator):
    decisions = [
        item
        for item in proposal["reviews"]
        if item["revisionId"] == revision["revisionId"]
        and item["revisionSha256"] == revision["revisionSha256"]
    ]
    if (
        proposal.get("status") != "review_complete"
        or len(decisions) != len(REVIEW_DOMAINS)
        or {item["domain"] for item in decisions} != REVIEW_DOMAINS
        or any(item["decision"] != "approved" for item in decisions)
        or len({item["reviewerId"] for item in decisions}) != len(REVIEW_DOMAINS)
        or proposal["authorId"] in {item["reviewerId"] for item in decisions}
        or operator in {item["reviewerId"] for item in decisions}
    ):
        raise StudyActivationError("study_not_permit_candidate", 409)
    return [
        {"domain": item["domain"], "decisionSha256": item["decisionSha256"]}
        for item in sorted(decisions, key=lambda item: item["domain"])
    ]


def release_binding(release):
    artifact_fields = (
        "purpose",
        "survey",
        "participantInformation",
        "protocol",
        "datasetView",
        "activationProfile",
        "taskPlan",
    )
    return {
        "dataUnionId": release["dataUnionId"],
        "offeringId": release["offeringId"],
        "offeringType": release["offeringType"],
        "releaseVersion": release["releaseVersion"],
        "releaseSha256": release["releaseSha256"],
        "artifacts": {field: deepcopy(release[field]) for field in artifact_fields},
    }


def _bundle(
    proposal,
    revision,
    decisions,
    release,
    activation_profile,
    permit_expires_at,
):
    value = {
        "schema": "brainstem.study-activation-bundle/v1",
        "proposal": {
            "proposalId": proposal["proposalId"],
            "revisionId": revision["revisionId"],
            "revisionSha256": revision["revisionSha256"],
        },
        "decisions": decisions,
        "release": release_binding(release),
        "activationProfile": deepcopy(activation_profile),
        "permitExpiresAt": rfc3339(permit_expires_at),
    }
    value["bundleSha256"] = content_sha256(value)
    return value


def _message(
    origin,
    operator,
    chain_id,
    nonce,
    challenge_id,
    issued_at,
    expires_at,
    bundle,
):
    profile = bundle["activationProfile"]["content"]
    limits = profile["limits"]
    decisions = ", ".join(
        "{}={}".format(item["domain"], item["decisionSha256"])
        for item in bundle["decisions"]
    )
    domain = urlparse(origin).netloc
    return "\n".join(
        [
            "{} requests a Brainstem study operator signature from:".format(domain),
            operator,
            "",
            (
                "Authorize one immutable study permit. This does not recruit, "
                "enroll, run compute, access participant data, or make a payment."
            ),
            "",
            "URI: {}/studies/operator".format(origin),
            "Version: 1",
            "Chain ID: {}".format(chain_id),
            "Nonce: {}".format(nonce),
            "Issued At: {}".format(rfc3339(issued_at)),
            "Expiration Time: {}".format(rfc3339(expires_at)),
            "Request ID: {}".format(challenge_id),
            "Purpose: {}".format(PURPOSE),
            "Proposal: {}".format(bundle["proposal"]["proposalId"]),
            "Revision: {}".format(bundle["proposal"]["revisionId"]),
            "Revision SHA256: {}".format(bundle["proposal"]["revisionSha256"]),
            "Approved Decisions: {}".format(decisions),
            "Offering Release SHA256: {}".format(bundle["release"]["releaseSha256"]),
            "Dataset Capability: {}".format(profile["datasetCapability"]),
            "Algorithm: {} {}".format(
                profile["algorithmId"], profile["algorithmVersion"]
            ),
            "Algorithm Source SHA256: {}".format(profile["algorithmSourceSha256"]),
            "Algorithm Image Digest: {}".format(profile["algorithmImageDigest"]),
            "Approved Manifest SHA256: {}".format(profile["approvedManifestSha256"]),
            "Reference SHA256: {}".format(profile["referenceSha256"]),
            "Result Contract: {} {}".format(
                profile["resultContractId"], profile["resultContractSha256"]
            ),
            "Operational Policy: {} {}".format(
                profile["operationalPolicyId"],
                profile["operationalPolicySha256"],
            ),
            "Environment: {} ({}, network={})".format(
                profile["environment"],
                profile["dataMode"],
                profile["algorithmNetwork"],
            ),
            "Limits SHA256: {}".format(content_sha256(limits)),
            "Permit Expiration: {}".format(bundle["permitExpiresAt"]),
            "Payment: {} {}".format(
                profile["payment"]["amountMinor"], profile["payment"]["currency"]
            ),
            "Activation Bundle SHA256: {}".format(bundle["bundleSha256"]),
        ]
    )


def public_permit(value):
    expected = {
        "schema",
        "permitId",
        "status",
        "operatorId",
        "challengeId",
        "proposalId",
        "revisionId",
        "revisionSha256",
        "bundle",
        "bundleSha256",
        "permittedAt",
        "expiresAt",
        "signedMessageSha256",
        "operatorSignatureSha256",
        "permitSha256",
    }
    bundle = value.get("bundle") if isinstance(value, dict) else None
    bundle_commitment = bundle.get("bundleSha256") if isinstance(bundle, dict) else None
    unsigned_bundle = (
        {key: item for key, item in bundle.items() if key != "bundleSha256"}
        if isinstance(bundle, dict)
        else {}
    )
    if (
        not isinstance(value, dict)
        or set(value) != expected
        or value.get("schema") != "brainstem.study-activation-permit/v1"
        or value.get("status") != "permitted"
        or not isinstance(value.get("permitId"), str)
        or not PERMIT_ID.fullmatch(value["permitId"])
        or value.get("permitId") != "permit_{}".format(value.get("challengeId"))
        or not isinstance(bundle, dict)
        or set(bundle)
        != {
            "schema",
            "proposal",
            "decisions",
            "release",
            "activationProfile",
            "permitExpiresAt",
            "bundleSha256",
        }
        or bundle.get("schema") != "brainstem.study-activation-bundle/v1"
        or not isinstance(bundle_commitment, str)
        or not SHA256.fullmatch(bundle_commitment)
        or not hmac.compare_digest(bundle_commitment, content_sha256(unsigned_bundle))
        or value.get("bundleSha256") != bundle_commitment
        or value.get("expiresAt") != bundle.get("permitExpiresAt")
        or value.get("proposalId") != bundle.get("proposal", {}).get("proposalId")
        or value.get("revisionId") != bundle.get("proposal", {}).get("revisionId")
        or value.get("revisionSha256")
        != bundle.get("proposal", {}).get("revisionSha256")
        or not isinstance(value.get("signedMessageSha256"), str)
        or not SHA256.fullmatch(value["signedMessageSha256"])
        or not isinstance(value.get("operatorSignatureSha256"), str)
        or not SHA256.fullmatch(value["operatorSignatureSha256"])
    ):
        raise StudyActivationError("study_activation_permit_invalid", 409)
    supplied = value.get("permitSha256")
    unsigned = {key: item for key, item in value.items() if key != "permitSha256"}
    if (
        not isinstance(supplied, str)
        or not SHA256.fullmatch(supplied)
        or not hmac.compare_digest(supplied, content_sha256(unsigned))
    ):
        raise StudyActivationError("study_activation_permit_invalid", 409)
    return deepcopy(value)


class StudyActivationService:
    def __init__(
        self,
        activation_dao,
        proposal_dao,
        registry,
        *,
        allowed_operators,
        allowed_origins,
        chain_id=11155420,
        challenge_ttl=300,
        clock=time.time,
        nonce_factory=lambda: secrets.token_urlsafe(32),
        id_factory=lambda: uuid.uuid4().hex,
    ):
        self.activation_dao = activation_dao
        self.proposal_dao = proposal_dao
        self.registry = registry
        self.allowed_operators = frozenset(_wallet(item) for item in allowed_operators)
        self.allowed_origins = tuple(item.rstrip("/") for item in allowed_origins)
        self.chain_id = int(chain_id)
        self.challenge_ttl = int(challenge_ttl)
        self.clock = clock
        self.nonce_factory = nonce_factory
        self.id_factory = id_factory
        if not self.allowed_operators or not self.allowed_origins:
            raise StudyActivationError("study_operator_configuration_invalid", 503)
        if not 1 <= self.chain_id or not 60 <= self.challenge_ttl <= MAX_CHALLENGE_TTL:
            raise StudyActivationError("study_operator_configuration_invalid", 503)

    def _operator(self, value):
        operator = _wallet(value)
        if operator not in self.allowed_operators:
            raise StudyActivationError("study_operator_forbidden", 403)
        return operator

    @staticmethod
    def _expected(revision_id, revision_sha256):
        if (
            not isinstance(revision_id, str)
            or not 1 <= len(revision_id) <= 80
            or not isinstance(revision_sha256, str)
            or not SHA256.fullmatch(revision_sha256)
        ):
            raise StudyActivationError("study_revision_commitment_required")

    def _candidate_parts(self, proposal_id, operator):
        proposal = self.proposal_dao.get(proposal_id)
        validate_stored_proposal(proposal)
        revision = _current_revision(proposal)
        decisions = _approved_decisions(proposal, revision, operator)
        release = self.registry.release(
            revision["offeringId"],
            revision["releaseVersion"],
            revision["releaseSha256"],
        )
        if release["offeringType"] not in {"study", "retrospective_study"}:
            raise StudyActivationError("study_not_permit_candidate", 409)
        profile = self.registry.activation_profile(
            revision["offeringId"],
            revision["releaseVersion"],
            revision["releaseSha256"],
        )
        return proposal, revision, decisions, release, profile

    def create_challenge(
        self,
        proposal_id,
        operator,
        origin,
        expected_revision_id,
        expected_revision_sha256,
    ):
        proposal_id = normalize_proposal_id(proposal_id)
        operator = self._operator(operator)
        origin = _strict_origin(origin, self.allowed_origins)
        self._expected(expected_revision_id, expected_revision_sha256)
        now = int(self.clock())
        challenge_id = self.id_factory()
        if not isinstance(challenge_id, str) or not CHALLENGE_ID.fullmatch(
            challenge_id
        ):
            raise RuntimeError("invalid generated activation challenge ID")
        expires_at = now + self.challenge_ttl
        candidate = self._candidate_parts(proposal_id, operator)
        profile_ttl = candidate[4]["content"]["permitTtlSeconds"]
        permit_expires_at = now + profile_ttl
        if permit_expires_at <= expires_at:
            raise StudyActivationError("study_operator_configuration_invalid", 503)
        bundle = _bundle(*candidate, permit_expires_at)
        if (
            bundle["proposal"]["revisionId"] != expected_revision_id
            or bundle["proposal"]["revisionSha256"] != expected_revision_sha256
        ):
            raise StudyProposalConflict("The study proposal changed concurrently")
        nonce = self.nonce_factory()
        if not isinstance(nonce, str) or not NONCE.fullmatch(nonce):
            raise RuntimeError("invalid generated activation challenge nonce")
        message = _message(
            origin,
            operator,
            self.chain_id,
            nonce,
            challenge_id,
            now,
            expires_at,
            bundle,
        )
        challenge = {
            "schema": "brainstem.study-activation-challenge/v1",
            "challenge_id": challenge_id,
            "proposal_id": proposal_id,
            "operator_id": operator,
            "origin": origin,
            "chain_id": self.chain_id,
            "purpose": PURPOSE,
            "nonce": nonce,
            "message": message,
            "bundle": bundle,
            "bundle_sha256": bundle["bundleSha256"],
            "issued_at": now,
            "expires_at": expires_at,
            "permit_expires_at": permit_expires_at,
            "consumed_at": None,
        }
        try:
            self.activation_dao.create_challenge(proposal_id, challenge, now)
        except StudyActivationStateError as error:
            status = 409 if "capacity" in str(error).lower() else 503
            raise StudyActivationError(
                "study_activation_challenge_unavailable", status
            ) from error
        return {
            "challengeId": challenge_id,
            "message": message,
            "expiresAt": rfc3339(expires_at),
            "permitExpiresAt": bundle["permitExpiresAt"],
            "chainId": self.chain_id,
            "method": "personal_sign",
            "bundle": deepcopy(bundle),
        }

    def apply(self, proposal_id, operator, origin, challenge_id, signature):
        proposal_id = normalize_proposal_id(proposal_id)
        operator = self._operator(operator)
        origin = _strict_origin(origin, self.allowed_origins)
        if not isinstance(challenge_id, str) or not CHALLENGE_ID.fullmatch(
            challenge_id
        ):
            raise StudyActivationError("study_activation_challenge_invalid")
        try:
            challenge = self.activation_dao.get_challenge(proposal_id, challenge_id)
        except StudyActivationStateError as error:
            raise StudyActivationError("study_activation_challenge_unavailable", 401) from error
        now = int(self.clock())
        if challenge.get("consumed_at") is not None:
            raise StudyActivationError("study_activation_challenge_used", 409)
        if (
            challenge.get("proposal_id") != proposal_id
            or challenge.get("operator_id") != operator
            or challenge.get("origin") != origin
            or challenge.get("chain_id") != self.chain_id
            or challenge.get("purpose") != PURPOSE
            or not isinstance(challenge.get("nonce"), str)
            or not NONCE.fullmatch(challenge["nonce"])
            or type(challenge.get("issued_at")) is not int
            or type(challenge.get("expires_at")) is not int
            or type(challenge.get("permit_expires_at")) is not int
            or not isinstance(challenge.get("bundle_sha256"), str)
            or not SHA256.fullmatch(challenge["bundle_sha256"])
        ):
            raise StudyActivationError("study_activation_challenge_unavailable", 401)
        if challenge["expires_at"] <= now:
            raise StudyActivationError("study_activation_challenge_expired", 410)
        if challenge["permit_expires_at"] <= now:
            raise StudyActivationError("study_activation_bundle_stale", 409)
        current_bundle = _bundle(
            *self._candidate_parts(proposal_id, operator),
            challenge["permit_expires_at"],
        )
        expected_message = _message(
            origin,
            operator,
            self.chain_id,
            challenge.get("nonce"),
            challenge_id,
            challenge.get("issued_at"),
            challenge.get("expires_at"),
            current_bundle,
        )
        if (
            challenge.get("bundle") != current_bundle
            or challenge.get("message") != expected_message
            or not hmac.compare_digest(
                challenge.get("bundle_sha256", ""), current_bundle["bundleSha256"]
            )
        ):
            raise StudyActivationError("study_activation_bundle_stale", 409)
        try:
            verify_wallet_signature(challenge["message"], signature, operator)
        except ParticipantAuthError as error:
            raise StudyActivationError(
                "study_operator_signature_invalid", error.status_code
            ) from error

        permit_id = "permit_{}".format(challenge_id)
        if not PERMIT_ID.fullmatch(permit_id):
            raise RuntimeError("invalid generated study permit ID")
        permit = {
            "schema": "brainstem.study-activation-permit/v1",
            "permitId": permit_id,
            "status": "permitted",
            "operatorId": operator,
            "challengeId": challenge_id,
            "proposalId": proposal_id,
            "revisionId": current_bundle["proposal"]["revisionId"],
            "revisionSha256": current_bundle["proposal"]["revisionSha256"],
            "bundle": current_bundle,
            "bundleSha256": current_bundle["bundleSha256"],
            "permittedAt": rfc3339(challenge["issued_at"]),
            "expiresAt": current_bundle["permitExpiresAt"],
            "signedMessageSha256": _text_sha256(challenge["message"]),
            "operatorSignatureSha256": _text_sha256(signature),
        }
        permit["permitSha256"] = content_sha256(permit)
        try:
            stored = self.activation_dao.consume_challenge_and_create_permit(
                proposal_id,
                challenge_id,
                current_bundle["bundleSha256"],
                permit,
                signature,
                now,
            )
        except StudyActivationStateError as error:
            status = 410 if "expired" in str(error).lower() else 409
            raise StudyActivationError(str(error), status) from error
        return public_permit(stored)

    def load_verified_permit(self, proposal_id, permit_id):
        proposal_id = normalize_proposal_id(proposal_id)
        if not isinstance(permit_id, str) or not PERMIT_ID.fullmatch(permit_id):
            raise StudyActivationError("study_activation_permit_invalid", 409)
        try:
            evidence = self.activation_dao.get_permit_evidence(
                proposal_id, permit_id
            )
        except StudyActivationStateError as error:
            raise StudyActivationError(
                "study_activation_evidence_unavailable", 409
            ) from error
        permit = public_permit(evidence.get("permit"))
        challenge = evidence.get("challenge")
        operator = self._operator(permit["operatorId"])
        expected_challenge_fields = {
            "schema",
            "challenge_id",
            "proposal_id",
            "operator_id",
            "origin",
            "chain_id",
            "purpose",
            "nonce",
            "message",
            "bundle",
            "bundle_sha256",
            "issued_at",
            "expires_at",
            "permit_expires_at",
            "consumed_at",
            "permit_id",
            "signature_sha256",
            "signature",
        }
        if (
            not isinstance(challenge, dict)
            or set(challenge) != expected_challenge_fields
            or challenge.get("schema") != "brainstem.study-activation-challenge/v1"
            or challenge.get("challenge_id") != permit["challengeId"]
            or challenge.get("proposal_id") != proposal_id
            or challenge.get("operator_id") != operator
            or challenge.get("chain_id") != self.chain_id
            or challenge.get("purpose") != PURPOSE
            or challenge.get("permit_id") != permit_id
            or challenge.get("bundle") != permit["bundle"]
            or challenge.get("bundle_sha256") != permit["bundleSha256"]
            or type(challenge.get("issued_at")) is not int
            or type(challenge.get("expires_at")) is not int
            or type(challenge.get("permit_expires_at")) is not int
            or type(challenge.get("consumed_at")) is not int
            or challenge["consumed_at"] < challenge["issued_at"]
            or permit.get("permittedAt") != rfc3339(challenge["issued_at"])
            or not isinstance(challenge.get("nonce"), str)
            or not NONCE.fullmatch(challenge["nonce"])
            or not isinstance(challenge.get("signature_sha256"), str)
            or not SHA256.fullmatch(challenge["signature_sha256"])
        ):
            raise StudyActivationError("study_activation_evidence_invalid", 409)
        verified_origin = _strict_origin(challenge.get("origin"), self.allowed_origins)
        signature_sha256 = _text_sha256(challenge.get("signature"))
        message_sha256 = _text_sha256(challenge.get("message"))
        if (
            not hmac.compare_digest(
                signature_sha256, challenge["signature_sha256"]
            )
            or not hmac.compare_digest(
                signature_sha256, permit["operatorSignatureSha256"]
            )
            or not hmac.compare_digest(
                message_sha256, permit["signedMessageSha256"]
            )
        ):
            raise StudyActivationError("study_activation_evidence_invalid", 409)
        try:
            source_bundle = _bundle(
                *self._candidate_parts(proposal_id, permit["operatorId"]),
                challenge["permit_expires_at"],
            )
        except (StudyProposalError, StudyRegistryError) as error:
            raise StudyActivationError(
                "study_activation_evidence_invalid", 409
            ) from error
        expected_message = _message(
            verified_origin,
            operator,
            self.chain_id,
            challenge["nonce"],
            challenge["challenge_id"],
            challenge["issued_at"],
            challenge["expires_at"],
            source_bundle,
        )
        if source_bundle != permit["bundle"] or challenge["message"] != expected_message:
            raise StudyActivationError("study_activation_evidence_invalid", 409)
        try:
            verify_wallet_signature(
                challenge["message"], challenge["signature"], permit["operatorId"]
            )
        except ParticipantAuthError as error:
            raise StudyActivationError("study_activation_evidence_invalid", 409) from error
        return permit
