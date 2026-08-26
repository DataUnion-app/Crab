"""Expiring operator signatures for one real eligibility or compute action."""

from copy import deepcopy
from datetime import datetime
import hashlib
import hmac
import re
import secrets
import time
import uuid
from urllib.parse import urlparse

from commands.dataunions.brainstem.c2d_export import FULL_NIGHT_SELECTOR_VERSION
from commands.dataunions.brainstem.study_activation import StudyActivationError
from commands.dataunions.studies.registry import content_sha256
from commands.users.participant_auth import (
    ParticipantAuthError,
    checksum_address,
    rfc3339,
    validate_origin,
    verify_wallet_signature,
)
from dao.study_activation_dao import StudyActivationStateError


ACTIONS = {"eligibility", "compute"}
CHALLENGE_ID = re.compile(r"^[0-9a-f]{32}$")
PERMIT_ID = re.compile(r"^data_permit_[0-9a-f]{32}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
IMAGE_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
NONCE = re.compile(r"^[A-Za-z0-9_-]{16,128}$")
MAX_TTL = 600
PURPOSE = "brainstem.study.data-action"


class StudyDataAuthorizationError(RuntimeError):
    def __init__(self, code, status_code=400):
        super().__init__(code)
        self.code = code
        self.status_code = status_code


def _parse_rfc3339(value):
    if not isinstance(value, str) or not value.endswith("Z"):
        raise StudyDataAuthorizationError("study_data_activation_permit_invalid", 409)
    try:
        parsed = int(datetime.fromisoformat(value[:-1] + "+00:00").timestamp())
    except ValueError as error:
        raise StudyDataAuthorizationError(
            "study_data_activation_permit_invalid", 409
        ) from error
    return parsed


def _message(origin, operator, chain_id, challenge):
    binding = challenge["binding"]
    decisions = ", ".join(
        f"{item['domain']}={item['decisionSha256']}" for item in binding["decisions"]
    )
    eligibility = binding["eligibilityReceiptSha256"] or "none"
    return "\n".join(
        [
            f"{urlparse(origin).netloc} requests a Brainstem study data signature from:",
            operator,
            "",
            "Authorize exactly one bounded data action. This expires and cannot recur.",
            "",
            f"URI: {origin}/studies/operator/data-actions",
            "Version: 1",
            f"Chain ID: {chain_id}",
            f"Nonce: {challenge['nonce']}",
            f"Issued At: {rfc3339(challenge['issued_at'])}",
            f"Expiration Time: {rfc3339(challenge['expires_at'])}",
            f"Request ID: {challenge['challenge_id']}",
            f"Purpose: {PURPOSE}",
            f"Action: {binding['action']}",
            f"Candidate Manifest SHA256: {binding['manifestSha256']}",
            f"Proposal: {binding['proposalId']}",
            f"Revision: {binding['revisionId']}",
            f"Revision SHA256: {binding['revisionSha256']}",
            f"Approved Decisions: {decisions}",
            f"Cohort Release: {binding['cohortReleaseId']}",
            f"Selector: {binding['selector']}",
            f"Protocol Release SHA256: {binding['releaseSha256']}",
            f"Algorithm Image Digest: {binding['algorithmImageDigest']}",
            f"Eligibility Receipt SHA256: {eligibility}",
            f"Binding SHA256: {challenge['binding_sha256']}",
        ]
    )


class StudyDataAuthorizationService:
    def __init__(
        self,
        activation_dao,
        activation_service,
        *,
        allowed_operators,
        allowed_origins,
        manifest_sha256,
        cohort_release_id,
        release_sha256,
        algorithm_image_digest,
        chain_id=11155420,
        challenge_ttl=300,
        clock=time.time,
        nonce_factory=lambda: secrets.token_urlsafe(32),
        id_factory=lambda: uuid.uuid4().hex,
    ):
        self.dao = activation_dao
        self.activation = activation_service
        try:
            self.operators = frozenset(
                checksum_address(item).lower() for item in allowed_operators
            )
        except ParticipantAuthError as error:
            raise StudyDataAuthorizationError(
                "study_data_authorization_configuration_invalid", 503
            ) from error
        self.origins = tuple(item.rstrip("/") for item in allowed_origins)
        self.manifest_sha256 = manifest_sha256
        self.cohort_release_id = cohort_release_id
        self.release_sha256 = release_sha256
        self.algorithm_image_digest = algorithm_image_digest
        self.chain_id = int(chain_id)
        self.challenge_ttl = int(challenge_ttl)
        self.clock = clock
        self.nonce_factory = nonce_factory
        self.id_factory = id_factory
        if (
            not self.operators
            or not self.origins
            or not SHA256.fullmatch(manifest_sha256 or "")
            or not SHA256.fullmatch(cohort_release_id or "")
            or not SHA256.fullmatch(release_sha256 or "")
            or not IMAGE_DIGEST.fullmatch(algorithm_image_digest or "")
            or self.chain_id < 1
            or not 60 <= self.challenge_ttl <= MAX_TTL
        ):
            raise StudyDataAuthorizationError(
                "study_data_authorization_configuration_invalid", 503
            )

    def _operator(self, value):
        try:
            operator = checksum_address(value).lower()
        except ParticipantAuthError as error:
            raise StudyDataAuthorizationError(
                "study_data_operator_forbidden", 403
            ) from error
        if operator not in self.operators:
            raise StudyDataAuthorizationError("study_data_operator_forbidden", 403)
        return operator

    def _origin(self, value):
        try:
            return validate_origin(value, self.origins)
        except ParticipantAuthError as error:
            raise StudyDataAuthorizationError(
                "study_data_origin_forbidden", 403
            ) from error

    def _activation_permit(self, proposal_id, permit_id, operator):
        try:
            permit = self.activation.load_verified_permit(proposal_id, permit_id)
        except StudyActivationError as error:
            raise StudyDataAuthorizationError(
                "study_data_activation_permit_invalid", 409
            ) from error
        if permit["operatorId"] != operator or _parse_rfc3339(permit["expiresAt"]) <= int(
            self.clock()
        ):
            raise StudyDataAuthorizationError(
                "study_data_activation_permit_invalid", 409
            )
        return permit

    def _binding(
        self,
        action,
        proposal_id,
        activation_permit_id,
        operator,
        eligibility_receipt_sha256,
    ):
        if action not in ACTIONS:
            raise StudyDataAuthorizationError("study_data_action_invalid")
        permit = self._activation_permit(proposal_id, activation_permit_id, operator)
        bundle = permit["bundle"]
        profile = bundle["activationProfile"]["content"]
        release = bundle["release"]
        binding = {
            "schema": "brainstem.study-data-action-binding/v1",
            "action": action,
            "manifestSha256": self.manifest_sha256,
            "proposalId": permit["proposalId"],
            "revisionId": permit["revisionId"],
            "revisionSha256": permit["revisionSha256"],
            "activationPermitId": permit["permitId"],
            "activationPermitSha256": permit["permitSha256"],
            "decisions": deepcopy(bundle["decisions"]),
            "cohortReleaseId": self.cohort_release_id,
            "selector": FULL_NIGHT_SELECTOR_VERSION,
            "offeringId": release["offeringId"],
            "releaseVersion": release["releaseVersion"],
            "releaseSha256": release["releaseSha256"],
            "algorithmImageDigest": profile["algorithmImageDigest"],
            "eligibilityReceiptSha256": eligibility_receipt_sha256,
        }
        if (
            binding["releaseSha256"] != self.release_sha256
            or binding["algorithmImageDigest"] != self.algorithm_image_digest
        ):
            raise StudyDataAuthorizationError("study_data_release_binding_invalid", 409)
        if action == "eligibility":
            if eligibility_receipt_sha256 is not None:
                raise StudyDataAuthorizationError("study_data_action_binding_invalid")
        else:
            if not SHA256.fullmatch(eligibility_receipt_sha256 or ""):
                raise StudyDataAuthorizationError("study_data_action_binding_invalid")
            try:
                receipt = self.dao.get_data_receipt(
                    proposal_id, eligibility_receipt_sha256
                )
                evidence = self.dao.get_data_permit_evidence(
                    proposal_id, receipt["permitId"]
                )
            except StudyActivationStateError as error:
                raise StudyDataAuthorizationError(
                    "study_data_eligibility_receipt_invalid", 409
                ) from error
            prior = evidence["permit"]["binding"]
            matching = (
                "manifestSha256",
                "proposalId",
                "revisionId",
                "revisionSha256",
                "activationPermitId",
                "activationPermitSha256",
                "decisions",
                "cohortReleaseId",
                "selector",
                "offeringId",
                "releaseVersion",
                "releaseSha256",
                "algorithmImageDigest",
            )
            if receipt["action"] != "eligibility" or any(
                prior.get(key) != binding[key] for key in matching
            ):
                raise StudyDataAuthorizationError(
                    "study_data_eligibility_receipt_invalid", 409
                )
        return binding

    def create_challenge(
        self,
        action,
        proposal_id,
        activation_permit_id,
        operator,
        origin,
        eligibility_receipt_sha256=None,
    ):
        operator = self._operator(operator)
        origin = self._origin(origin)
        binding = self._binding(
            action,
            proposal_id,
            activation_permit_id,
            operator,
            eligibility_receipt_sha256,
        )
        challenge_id = self.id_factory()
        nonce = self.nonce_factory()
        if not CHALLENGE_ID.fullmatch(challenge_id or "") or not NONCE.fullmatch(
            nonce or ""
        ):
            raise RuntimeError("invalid generated data action challenge")
        now = int(self.clock())
        challenge = {
            "schema": "brainstem.study-data-action-challenge/v1",
            "challenge_id": challenge_id,
            "proposal_id": proposal_id,
            "operator_id": operator,
            "origin": origin,
            "chain_id": self.chain_id,
            "purpose": PURPOSE,
            "nonce": nonce,
            "issued_at": now,
            "expires_at": now + self.challenge_ttl,
            "binding": binding,
            "binding_sha256": content_sha256(binding),
            "message": None,
            "consumed_at": None,
        }
        challenge["message"] = _message(origin, operator, self.chain_id, challenge)
        try:
            self.dao.create_data_challenge(proposal_id, challenge, now)
        except StudyActivationStateError as error:
            raise StudyDataAuthorizationError(str(error), 409) from error
        return {
            "challengeId": challenge_id,
            "message": challenge["message"],
            "expiresAt": rfc3339(challenge["expires_at"]),
            "chainId": self.chain_id,
            "method": "personal_sign",
            "binding": deepcopy(binding),
        }

    def apply(self, proposal_id, operator, origin, challenge_id, signature):
        operator = self._operator(operator)
        origin = self._origin(origin)
        if not CHALLENGE_ID.fullmatch(challenge_id or ""):
            raise StudyDataAuthorizationError("study_data_challenge_invalid")
        try:
            challenge = self.dao.get_data_challenge(proposal_id, challenge_id)
        except StudyActivationStateError as error:
            raise StudyDataAuthorizationError(
                "study_data_challenge_unavailable", 401
            ) from error
        now = int(self.clock())
        binding = challenge.get("binding")
        if (
            challenge.get("schema") != "brainstem.study-data-action-challenge/v1"
            or challenge.get("proposal_id") != proposal_id
            or challenge.get("operator_id") != operator
            or challenge.get("origin") != origin
            or challenge.get("chain_id") != self.chain_id
            or challenge.get("purpose") != PURPOSE
            or challenge.get("consumed_at") is not None
            or challenge.get("expires_at", 0) <= now
            or not isinstance(binding, dict)
            or challenge.get("binding_sha256") != content_sha256(binding)
            or challenge.get("message") != _message(origin, operator, self.chain_id, challenge)
        ):
            raise StudyDataAuthorizationError("study_data_challenge_invalid", 409)
        current = self._binding(
            binding.get("action"),
            proposal_id,
            binding.get("activationPermitId"),
            operator,
            binding.get("eligibilityReceiptSha256"),
        )
        if current != binding:
            raise StudyDataAuthorizationError("study_data_binding_stale", 409)
        try:
            verify_wallet_signature(challenge["message"], signature, operator)
        except ParticipantAuthError as error:
            raise StudyDataAuthorizationError(
                "study_data_signature_invalid", error.status_code
            ) from error
        permit = {
            "schema": "brainstem.study-data-action-permit/v1",
            "permitId": "data_permit_" + challenge_id,
            "challengeId": challenge_id,
            "operatorId": operator,
            "action": binding["action"],
            "binding": binding,
            "bindingSha256": challenge["binding_sha256"],
            "permittedAt": now,
            "expiresAt": challenge["expires_at"],
            "signedMessageSha256": hashlib.sha256(
                challenge["message"].encode()
            ).hexdigest(),
            "operatorSignatureSha256": hashlib.sha256(signature.encode()).hexdigest(),
            "permitSha256": None,
        }
        permit["permitSha256"] = content_sha256(
            {key: value for key, value in permit.items() if key != "permitSha256"}
        )
        try:
            return self.dao.consume_data_challenge(
                proposal_id,
                challenge_id,
                challenge["binding_sha256"],
                permit,
                signature,
                now,
            )
        except StudyActivationStateError as error:
            raise StudyDataAuthorizationError(str(error), 409) from error

    def _verified_permit(self, proposal_id, permit_id, action):
        if not PERMIT_ID.fullmatch(permit_id or "") or action not in ACTIONS:
            raise StudyDataAuthorizationError("study_data_permit_invalid", 409)
        try:
            evidence = self.dao.get_data_permit_evidence(proposal_id, permit_id)
        except StudyActivationStateError as error:
            raise StudyDataAuthorizationError("study_data_permit_invalid", 409) from error
        permit, challenge = evidence["permit"], evidence["challenge"]
        unsigned = {key: value for key, value in permit.items() if key != "permitSha256"}
        permit_fields = {
            "schema",
            "permitId",
            "challengeId",
            "operatorId",
            "action",
            "binding",
            "bindingSha256",
            "permittedAt",
            "expiresAt",
            "signedMessageSha256",
            "operatorSignatureSha256",
            "permitSha256",
        }
        try:
            message_matches = challenge.get("message") == _message(
                challenge["origin"], permit["operatorId"], self.chain_id, challenge
            )
        except (KeyError, TypeError):
            message_matches = False
        if (
            set(permit) != permit_fields
            or permit.get("schema") != "brainstem.study-data-action-permit/v1"
            or permit.get("permitId") != permit_id
            or permit.get("action") != action
            or permit.get("permitSha256") != content_sha256(unsigned)
            or permit.get("bindingSha256") != content_sha256(permit.get("binding"))
            or permit.get("challengeId") != challenge.get("challenge_id")
            or challenge.get("permit_id") != permit_id
            or challenge.get("binding") != permit.get("binding")
            or challenge.get("binding_sha256") != permit.get("bindingSha256")
            or challenge.get("signature_sha256")
            != permit.get("operatorSignatureSha256")
            or hashlib.sha256(challenge.get("message", "").encode()).hexdigest()
            != permit.get("signedMessageSha256")
            or hashlib.sha256(challenge.get("signature", "").encode()).hexdigest()
            != permit.get("operatorSignatureSha256")
            or not message_matches
        ):
            raise StudyDataAuthorizationError("study_data_permit_invalid", 409)
        operator = self._operator(permit["operatorId"])
        current = self._binding(
            action,
            proposal_id,
            permit["binding"]["activationPermitId"],
            operator,
            permit["binding"]["eligibilityReceiptSha256"],
        )
        if current != permit["binding"] or permit["expiresAt"] <= int(self.clock()):
            raise StudyDataAuthorizationError("study_data_permit_expired", 410)
        try:
            verify_wallet_signature(challenge["message"], challenge["signature"], operator)
        except ParticipantAuthError as error:
            raise StudyDataAuthorizationError("study_data_permit_invalid", 409) from error
        return permit

    def execute(self, proposal_id, permit_id, action, execution_id, callback):
        permit = self._verified_permit(proposal_id, permit_id, action)
        execution_sha256 = hashlib.sha256(execution_id.encode()).hexdigest()
        now = int(self.clock())
        try:
            claim = self.dao.claim_data_permit(
                proposal_id, permit_id, action, execution_sha256, now
            )
        except StudyActivationStateError as error:
            raise StudyDataAuthorizationError(str(error), 409) from error
        value = callback(deepcopy(permit["binding"]))
        if isinstance(value, bytes):
            result_sha256 = hashlib.sha256(value).hexdigest()
        elif isinstance(value, dict):
            result_sha256 = content_sha256(value)
        elif isinstance(getattr(value, "body", None), bytes):
            result_sha256 = hashlib.sha256(value.body).hexdigest()
        else:
            raise StudyDataAuthorizationError("study_data_result_invalid", 500)
        try:
            receipt = self.dao.finalize_data_permit(
                proposal_id,
                permit_id,
                claim["receiptSha256"],
                result_sha256,
                int(self.clock()),
            )
        except StudyActivationStateError as error:
            raise StudyDataAuthorizationError("study_data_receipt_failed", 503) from error
        return value, deepcopy(receipt)
