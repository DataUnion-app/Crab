"""Signed participant actions over the immutable study registry."""

from copy import deepcopy
import hashlib
import hmac
import json
import re
import secrets
import threading
import time
import uuid
from urllib.parse import urlparse

from commands.dataunions.brainstem.consent import has_brainstem_data_consent
from commands.dataunions.brainstem.study_fixtures import (
    APDET_DIAGNOSIS_QUESTIONNAIRE_ID,
    DEFAULT_STUDY_REGISTRY,
    RECORDING_FEASIBILITY_ID,
)
from commands.dataunions.brainstem.study_operations import StudyOperationsError
from commands.dataunions.brainstem.study_recurring import (
    block_recurring_for_renewal,
    scrub_recurring,
)
from commands.dataunions.studies.registry import (
    StudyRegistryError,
    content_sha256,
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
ACTIONS = {"answer", "enroll", "withdraw", "delete"}
MAX_HISTORY = 50
MAX_ACTION_HISTORY = 100
PURPOSE = "brainstem.study-offering/action/v2"
RESOURCE_PREFIX = "urn:brainstem:study-offering:"
ENROLLMENT_EVIDENCE_SCHEMA = "brainstem.study-enrollment-evidence/v2"
STUDY_PROPOSAL_ID = re.compile(r"^study_[0-9a-f]{1,64}$")
STUDY_PERMIT_ID = re.compile(r"^permit_[0-9a-f]{32}$")
MIN_RECRUITMENT_TTL = 60
MAX_RECRUITMENT_TTL = 600
MEMBER_ONLY_OFFERINGS = frozenset({APDET_DIAGNOSIS_QUESTIONNAIRE_ID})


class GenericStudyServiceError(RuntimeError):
    def __init__(self, code, status_code=400):
        super().__init__(code)
        self.code = code
        self.status_code = status_code


def _valid_hash(value):
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _valid_binding_key_id(value):
    return (
        isinstance(value, str)
        and 1 <= len(value) <= 64
        and value.isascii()
        and all(character.isalnum() or character in "._-" for character in value)
    )


def _participant_binding_secret_bytes(secret):
    if not _valid_hash(secret):
        raise GenericStudyServiceError(
            "participant_binding_configuration_invalid", 503
        )
    try:
        decoded = bytes.fromhex(secret)
    except ValueError as error:
        raise GenericStudyServiceError(
            "participant_binding_configuration_invalid", 503
        ) from error
    if len(decoded) != 32:
        raise GenericStudyServiceError(
            "participant_binding_configuration_invalid", 503
        )
    return decoded


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
        raise GenericStudyServiceError("origin_invalid")
    return value


def _response_hash(value):
    fields = {
        key: value.get(key)
        for key in (
            "schema",
            "offeringId",
            "releaseVersion",
            "releaseSha256",
            "surveyVersion",
            "surveySha256",
            "revision",
            "answers",
            "answersSha256",
            "submittedAt",
            "supersedes",
        )
    }
    return content_sha256(fields)


def create_response(
    registry,
    offering_id,
    answers,
    *,
    submitted_at,
    previous=None,
    release_version=None,
):
    release = registry.release(offering_id, release_version)
    normalized = registry.validate_answers(
        offering_id,
        answers,
        release["releaseVersion"],
        release["releaseSha256"],
    )
    if not isinstance(submitted_at, int) or isinstance(submitted_at, bool):
        raise GenericStudyServiceError("survey_time_invalid")
    if previous is not None:
        validate_response(registry, offering_id, previous)
        if previous["state"] != "active":
            raise GenericStudyServiceError("survey_revision_unavailable", 409)
        if (
            previous["releaseSha256"] == release["releaseSha256"]
            and previous["answersSha256"] == content_sha256(normalized)
        ):
            return deepcopy(previous)
        revision = previous["revision"] + 1
        supersedes = previous["revisionSha256"]
    else:
        revision = 1
        supersedes = None
    value = {
        "schema": "brainstem.study-response/v1",
        "offeringId": offering_id,
        "releaseVersion": release["releaseVersion"],
        "releaseSha256": release["releaseSha256"],
        "surveyVersion": release["survey"]["version"],
        "surveySha256": release["survey"]["sha256"],
        "revision": revision,
        "state": "active",
        "evidenceSource": registry.artifact(release["survey"])["content"][
            "evidenceSource"
        ],
        "answers": normalized,
        "answersSha256": content_sha256(normalized),
        "submittedAt": submitted_at,
        "supersedes": supersedes,
        "withdrawnAt": None,
        "deletedAt": None,
    }
    value["revisionSha256"] = _response_hash(value)
    return value


def validate_response(registry, offering_id, value):
    if not isinstance(value, dict) or value.get("offeringId") != offering_id:
        raise GenericStudyServiceError("survey_revision_invalid")
    if value.get("schema") == "brainstem.study-response-deletion-tombstone/v2":
        if (
            set(value)
            != {"schema", "offeringId", "revision", "state", "deletedOn"}
            or value.get("state") != "deleted"
            or type(value.get("revision")) is not int
            or value["revision"] < 1
        ):
            raise GenericStudyServiceError("survey_revision_invalid")
        try:
            parsed = time.strptime(value.get("deletedOn"), "%Y-%m-%d")
        except (TypeError, ValueError) as error:
            raise GenericStudyServiceError("survey_revision_invalid") from error
        if time.strftime("%Y-%m-%d", parsed) != value["deletedOn"]:
            raise GenericStudyServiceError("survey_revision_invalid")
        return value
    release_version = value.get("releaseVersion")
    release_sha256 = value.get("releaseSha256")
    try:
        release = registry.release(offering_id, release_version, release_sha256)
    except StudyRegistryError as error:
        raise GenericStudyServiceError("survey_revision_invalid") from error
    common = {
        "schema": "brainstem.study-response/v1",
        "offeringId": offering_id,
        "releaseVersion": release["releaseVersion"],
        "releaseSha256": release["releaseSha256"],
        "surveyVersion": release["survey"]["version"],
        "surveySha256": release["survey"]["sha256"],
    }
    if any(value.get(key) != item for key, item in common.items()):
        raise GenericStudyServiceError("survey_revision_invalid")
    if (
        value.get("state") not in {"active", "superseded", "withdrawn", "deleted"}
        or not isinstance(value.get("revision"), int)
        or isinstance(value.get("revision"), bool)
        or value["revision"] < 1
        or not isinstance(value.get("submittedAt"), int)
        or isinstance(value.get("submittedAt"), bool)
    ):
        raise GenericStudyServiceError("survey_revision_invalid")
    if value["state"] == "deleted":
        if set(value) != {
            "schema",
            "offeringId",
            "releaseVersion",
            "releaseSha256",
            "surveyVersion",
            "surveySha256",
            "revision",
            "state",
            "evidenceSource",
            "submittedAt",
            "deletedAt",
        }:
            raise GenericStudyServiceError("survey_revision_invalid")
        return value
    try:
        answers = registry.validate_answers(
            offering_id,
            value.get("answers"),
            release["releaseVersion"],
            release["releaseSha256"],
        )
    except StudyRegistryError as error:
        raise GenericStudyServiceError(str(error), 422) from error
    if (
        value.get("answersSha256") != content_sha256(answers)
        or not _valid_hash(value.get("revisionSha256"))
        or value["revisionSha256"] != _response_hash(value)
    ):
        raise GenericStudyServiceError("survey_revision_invalid")
    return value


def participant_response(value):
    if not isinstance(value, dict):
        return None
    if value.get("schema") == "brainstem.study-response-deletion-tombstone/v2":
        return {
            "surveyVersion": None,
            "releaseVersion": None,
            "releaseSha256": None,
            "revision": value["revision"],
            "state": "deleted",
            "evidenceSource": None,
            "answers": None,
            "submittedAt": None,
            "withdrawnAt": None,
            "deletedAt": None,
            "deletedOn": value["deletedOn"],
        }
    return {
        "surveyVersion": value["surveyVersion"],
        "releaseVersion": value["releaseVersion"],
        "releaseSha256": value["releaseSha256"],
        "revision": value["revision"],
        "state": value["state"],
        "evidenceSource": value["evidenceSource"],
        "answers": deepcopy(value.get("answers")),
        "submittedAt": value["submittedAt"],
        "withdrawnAt": value.get("withdrawnAt"),
        "deletedAt": value.get("deletedAt"),
    }


def _superseded(value):
    result = deepcopy(value)
    result["state"] = "superseded"
    return result


def _deleted(value, now):
    if value.get("schema") == "brainstem.study-response-deletion-tombstone/v2":
        return deepcopy(value)
    return {
        "schema": "brainstem.study-response-deletion-tombstone/v2",
        "offeringId": value["offeringId"],
        "revision": value["revision"],
        "state": "deleted",
        "deletedOn": time.strftime("%Y-%m-%d", time.gmtime(now)),
    }


def _eligible(offering_id, response):
    if response is None or response.get("state") != "active":
        return False
    if offering_id != RECORDING_FEASIBILITY_ID:
        return True
    answers = response.get("answers", {})
    return answers.get("adult_status") == "yes"


def _enrollment_sha256(value):
    return content_sha256(
        {key: item for key, item in value.items() if key != "enrollmentSha256"}
    )


def _participant_binding(
    secret,
    key_id,
    user_id,
    offering_id,
    release_sha256,
):
    if not _valid_binding_key_id(key_id):
        raise GenericStudyServiceError(
            "participant_binding_configuration_invalid", 503
        )
    secret_bytes = _participant_binding_secret_bytes(secret)
    if not isinstance(user_id, str) or not user_id:
        raise GenericStudyServiceError("participant_identity_invalid", 409)
    if (
        not isinstance(offering_id, str)
        or not offering_id
        or not _valid_hash(release_sha256)
    ):
        raise GenericStudyServiceError("participant_identity_scope_invalid", 409)
    scope = json.dumps(
        [
            "brainstem.study.participant/v2",
            key_id,
            offering_id,
            release_sha256,
            user_id,
        ],
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return hmac.new(secret_bytes, scope, hashlib.sha256).hexdigest()


def _participant_binding_secret_commitment(
    secret, key_id, offering_id, release_sha256
):
    if (
        not _valid_binding_key_id(key_id)
        or not isinstance(offering_id, str)
        or not offering_id
        or not _valid_hash(release_sha256)
    ):
        raise GenericStudyServiceError(
            "participant_binding_configuration_invalid", 503
        )
    secret_bytes = _participant_binding_secret_bytes(secret)
    scope = json.dumps(
        [
            "brainstem.study.participant-binding-key/v2",
            key_id,
            offering_id,
            release_sha256,
        ],
        separators=(",", ":"),
    ).encode("ascii")
    return hmac.new(secret_bytes, scope, hashlib.sha256).hexdigest()


def _recruitment_reservation_key(challenge_id):
    if not isinstance(challenge_id, str) or not IDENTIFIER.fullmatch(challenge_id):
        raise GenericStudyServiceError("challenge_unavailable", 401)
    return hashlib.sha256(
        ("brainstem.study.recruitment-reservation/v1\0" + challenge_id).encode(
            "ascii"
        )
    ).hexdigest()


def _message(origin, address, challenge):
    action = challenge["action"]
    statement = {
        "answer": "Save these voluntary answers. This does not join a study or authorize another use.",
        "enroll": "Join this candidate generated-only study under the exact release shown.",
        "withdraw": "Leave this study and stop prospective collection under this release.",
        "delete": "Delete this response content, leave a versioned tombstone, and exclude future use.",
    }[action]
    return "\n".join(
        [
            "{} requests a Brainstem study action with your Ethereum account:".format(
                urlparse(origin).netloc
            ),
            address,
            "",
            statement,
            "",
            "URI: {}/participant/studies/{}".format(origin, challenge["offeringId"]),
            "Version: 1",
            "Chain ID: {}".format(CHAIN_ID),
            "Nonce: {}".format(challenge["nonce"]),
            "Issued At: {}".format(rfc3339(challenge["issuedAt"])),
            "Expiration Time: {}".format(rfc3339(challenge["expiresAt"])),
            "Request ID: {}".format(challenge["challengeId"]),
            "Purpose: {}".format(PURPOSE),
            "Scope: participant:self:study:{}".format(action),
            "Action: {}".format(action),
            "Data Union: {}".format(challenge["dataUnionId"]),
            "Offering: {}".format(challenge["offeringId"]),
            "Release Version: {}".format(challenge["releaseVersion"]),
            "Release SHA256: {}".format(challenge["releaseSha256"]),
            "Purpose Artifact SHA256: {}".format(
                challenge["artifactRefs"]["purpose"]["sha256"]
            ),
            "Survey Artifact SHA256: {}".format(
                challenge["artifactRefs"]["survey"]["sha256"]
            ),
            "Participant Information Artifact SHA256: {}".format(
                challenge["artifactRefs"]["participantInformation"]["sha256"]
            ),
            "Protocol Artifact SHA256: {}".format(
                (challenge["artifactRefs"]["protocol"] or {}).get("sha256", "none")
            ),
            "Dataset View Artifact SHA256: {}".format(
                (challenge["artifactRefs"]["datasetView"] or {}).get("sha256", "none")
            ),
            "Activation Profile Artifact SHA256: {}".format(
                (challenge["artifactRefs"]["activationProfile"] or {}).get(
                    "sha256", "none"
                )
            ),
            "Task Plan Artifact SHA256: {}".format(
                (challenge["artifactRefs"]["taskPlan"] or {}).get("sha256", "none")
            ),
            "Participant Binding SHA256: {}".format(
                challenge["participantBindingSha256"] or "none"
            ),
            "Participant Binding Key ID: {}".format(
                challenge["participantBindingKeyId"] or "none"
            ),
            "Participant Binding Key Commitment SHA256: {}".format(
                challenge["participantBindingKeyCommitmentSha256"] or "none"
            ),
            "Proposal: {}".format(
                (challenge.get("operations") or {}).get("proposalId", "none")
            ),
            "Permit: {}".format(
                (challenge.get("operations") or {}).get("permitId", "none")
            ),
            "Operation State SHA256: {}".format(
                (challenge.get("operations") or {}).get(
                    "operationStateSha256", "none"
                )
            ),
            "Recruitment Ticket TTL Seconds: {}".format(
                (challenge.get("operations") or {}).get(
                    "recruitmentTicketTtlSeconds", "none"
                )
            ),
            "Study Starts At: {}".format(
                rfc3339((challenge.get("operations") or {}).get("startsAt"))
                if isinstance(
                    (challenge.get("operations") or {}).get("startsAt"), int
                )
                else "none"
            ),
            "Study Ends At: {}".format(
                rfc3339((challenge.get("operations") or {}).get("endsAt"))
                if isinstance(
                    (challenge.get("operations") or {}).get("endsAt"), int
                )
                else "none"
            ),
            "Target SHA256: {}".format(challenge["targetSha256"] or "none"),
            "Payment: none",
            "Resources:",
            "- {}{}".format(RESOURCE_PREFIX, challenge["offeringId"]),
        ]
    )


class PendingAnswerStore:
    """Process-local, short-lived answer staging for the generated-only slice."""

    def __init__(self):
        self._values = {}
        self._lock = threading.Lock()

    def _prune(self, now):
        expired = [
            key
            for key, value in self._values.items()
            if value["expiresAt"] <= now
        ]
        for key in expired:
            self._values.pop(key, None)

    def put(self, challenge_id, response, expires_at, now):
        with self._lock:
            self._prune(now)
            self._values[challenge_id] = {
                "response": deepcopy(response),
                "expiresAt": expires_at,
            }

    def get(self, challenge_id, now):
        with self._lock:
            self._prune(now)
            value = self._values.get(challenge_id)
            return deepcopy(value["response"]) if value else None

    def discard(self, challenge_id, now):
        with self._lock:
            self._prune(now)
            self._values.pop(challenge_id, None)


class GenericStudyService:
    def __init__(
        self,
        auth,
        dao,
        registry=DEFAULT_STUDY_REGISTRY,
        clock=time.time,
        id_factory=lambda: uuid.uuid4().hex,
        nonce_factory=lambda: secrets.token_urlsafe(32),
        pending_answers=None,
        operations=None,
        task_completion_source=None,
        participant_binding_secret=None,
        participant_binding_key_id=None,
        offering_access=None,
        available_offerings=None,
    ):
        self.auth = auth
        self.dao = dao
        self.registry = registry
        self.clock = clock
        self.id_factory = id_factory
        self.nonce_factory = nonce_factory
        self.pending_answers = pending_answers or PendingAnswerStore()
        self.operations = operations
        self.task_completion_source = task_completion_source
        self.participant_binding_secret = participant_binding_secret or getattr(
            operations, "participant_binding_secret", None
        )
        self.participant_binding_key_id = participant_binding_key_id or getattr(
            operations, "participant_binding_key_id", None
        )
        self.offering_access = offering_access
        self.available_offerings = (
            None
            if available_offerings is None
            else frozenset(available_offerings)
        )

    def _participant(self, token, origin):
        _session_id, _session, user = self.auth.authenticate(token, origin)
        return user

    def _require_offering_access(self, offering_id, user):
        if (
            self.available_offerings is not None
            and offering_id not in self.available_offerings
        ):
            raise GenericStudyServiceError("offering_unavailable", 404)
        if offering_id in MEMBER_ONLY_OFFERINGS and (
            self.offering_access is None
            or not self.offering_access(offering_id, user)
        ):
            raise GenericStudyServiceError("offering_unavailable", 404)

    def _state(self, user_id, user=None):
        state = self.dao.get_state(user_id) or {}
        challenge = state.get("genericChallenge")
        now = int(self.clock())
        if (
            isinstance(challenge, dict)
            and isinstance(challenge.get("expiresAt"), int)
            and challenge["expiresAt"] <= now
        ):
            challenge_id = challenge.get("challengeId")

            if (
                challenge.get("action") == "enroll"
                and challenge.get("consumedAt") is None
                and self.operations is not None
            ):
                try:
                    reconciled = self.operations.cancel_recruitment_reservation(
                        (challenge.get("operations") or {}).get("proposalId"),
                        _recruitment_reservation_key(challenge_id),
                    )
                except (GenericStudyServiceError, StudyOperationsError):
                    reconciled = False
                if reconciled is False:
                    raise GenericStudyServiceError(
                        "study_recruitment_reconciliation_pending", 503
                    )

            if (
                challenge.get("action") == "enroll"
                and challenge.get("consumedAt") is not None
            ):
                enrollment = self._offering_state(
                    state, challenge.get("offeringId")
                ).get("enrollment")
                if isinstance(enrollment, dict):
                    state = self._recover_consumed_enrollment(
                        user_id,
                        state,
                        challenge,
                        enrollment,
                        user,
                    )
                    challenge_id = None

            def remove_expired(value):
                current = value.get("genericChallenge")
                if (
                    isinstance(current, dict)
                    and current.get("challengeId") == challenge_id
                    and current.get("expiresAt", now + 1) <= now
                ):
                    value.pop("genericChallenge", None)
                return value

            if challenge_id is not None:
                state = self.dao.mutate_state(user_id, remove_expired)
            if challenge_id:
                self.pending_answers.discard(challenge_id, now)
        if self.operations is not None:
            renewals = []
            for offering_id, private in state.get("offerings", {}).items():
                enrollment = private.get("enrollment") if isinstance(private, dict) else None
                pending = state.get("genericChallenge")
                if (
                    isinstance(pending, dict)
                    and pending.get("action") == "enroll"
                    and pending.get("offeringId") == offering_id
                    and pending.get("consumedAt") is not None
                ):
                    continue
                if (
                    isinstance(enrollment, dict)
                    and enrollment.get("state") == "active"
                ):
                    try:
                        verified = self.load_verified_enrollment(
                            user_id,
                            offering_id,
                            state=state,
                            user=user,
                        )
                        renewal_required = self.operations.enrollment_requires_renewal(
                            verified
                        )
                    except GenericStudyServiceError:
                        renewal_required = True
                    if renewal_required:
                        renewals.append(
                            (offering_id, enrollment.get("enrollmentSha256"))
                        )
            if renewals:
                expected = dict(renewals)

                def require_renewal(value):
                    offerings = value.get("offerings", {})
                    for offering_id, enrollment_sha256 in expected.items():
                        enrollment = offerings.get(offering_id, {}).get("enrollment")
                        if (
                            isinstance(enrollment, dict)
                            and enrollment.get("state") == "active"
                            and enrollment.get("enrollmentSha256") == enrollment_sha256
                        ):
                            enrollment = deepcopy(enrollment)
                            enrollment["state"] = "renewal_required"
                            enrollment["renewalRequiredAt"] = now
                            enrollment["enrollmentSha256"] = _enrollment_sha256(
                                enrollment
                            )
                            offerings[offering_id]["enrollment"] = enrollment
                            block_recurring_for_renewal(
                                offerings[offering_id]
                            )
                    return value

                state = self.dao.mutate_state(user_id, require_renewal)
        return state

    def _recruitment_contract(
        self,
        release,
        participant_binding_sha256,
        participant_binding_key_id,
        participant_binding_key_commitment_sha256,
        now,
    ):
        if self.operations is None:
            raise GenericStudyServiceError("study_operations_unavailable", 503)
        try:
            contract = self.operations.recruitment_contract(
                release["offeringId"],
                release["releaseSha256"],
                now,
                participant_binding_key_id,
                participant_binding_key_commitment_sha256,
            )
        except StudyOperationsError as error:
            raise GenericStudyServiceError(error.code, error.status_code) from error
        return {**contract, "participantBindingSha256": participant_binding_sha256}

    def _reserve_recruitment(
        self,
        release,
        participant_binding_sha256,
        participant_binding_key_id,
        participant_binding_key_commitment_sha256,
        signed_contract,
        reservation_key_sha256,
        consumed_at,
    ):
        try:
            reserved = self.operations.reserve_recruitment(
                release["offeringId"],
                release["releaseSha256"],
                participant_binding_sha256,
                participant_binding_key_id,
                participant_binding_key_commitment_sha256,
                reservation_key_sha256,
                consumed_at,
            )
        except StudyOperationsError as error:
            raise GenericStudyServiceError(error.code, error.status_code) from error
        self._validate_reserved_contract(
            reserved,
            release,
            participant_binding_sha256,
            participant_binding_key_id,
            participant_binding_key_commitment_sha256,
            signed_contract,
            reservation_key_sha256,
            consumed_at,
        )
        return reserved

    @staticmethod
    def _validate_operations_contract(
        value,
        release,
        participant_binding_sha256,
        participant_binding_key_id,
        participant_binding_key_commitment_sha256,
    ):
        expected = {
            "proposalId",
            "permitId",
            "operationStateSha256",
            "taskPlan",
            "startsAt",
            "endsAt",
            "participantBindingKeyId",
            "participantBindingKeyCommitmentSha256",
            "participantBindingSha256",
            "recruitmentTicketTtlSeconds",
        }
        if (
            not isinstance(value, dict)
            or set(value) != expected
            or not isinstance(value.get("proposalId"), str)
            or not STUDY_PROPOSAL_ID.fullmatch(value["proposalId"])
            or not isinstance(value.get("permitId"), str)
            or not STUDY_PERMIT_ID.fullmatch(value["permitId"])
            or not _valid_hash(value.get("operationStateSha256"))
            or value.get("taskPlan") != release["taskPlan"]
            or type(value.get("startsAt")) is not int
            or type(value.get("endsAt")) is not int
            or value["endsAt"] <= value["startsAt"]
            or value.get("participantBindingKeyId")
            != participant_binding_key_id
            or value.get("participantBindingKeyCommitmentSha256")
            != participant_binding_key_commitment_sha256
            or value.get("participantBindingSha256")
            != participant_binding_sha256
            or type(value.get("recruitmentTicketTtlSeconds")) is not int
            or not MIN_RECRUITMENT_TTL
            <= value["recruitmentTicketTtlSeconds"]
            <= MAX_RECRUITMENT_TTL
        ):
            raise GenericStudyServiceError(
                "study_recruitment_contract_invalid", 409
            )
        return value

    @classmethod
    def _validate_reserved_contract(
        cls,
        value,
        release,
        participant_binding_sha256,
        participant_binding_key_id,
        participant_binding_key_commitment_sha256,
        signed_contract,
        reservation_key_sha256,
        consumed_at,
    ):
        ticket_fields = {
            "recruitmentTicketId",
            "recruitmentTicketSha256",
            "recruitmentTicketIssuedAt",
            "recruitmentTicketExpiresAt",
            "recruitmentReservationKeySha256",
        }
        if (
            not isinstance(value, dict)
            or set(value) != set(signed_contract) | ticket_fields
            or {key: value.get(key) for key in signed_contract}
            != signed_contract
            or not isinstance(value.get("recruitmentTicketId"), str)
            or not IDENTIFIER.fullmatch(value["recruitmentTicketId"])
            or not _valid_hash(value.get("recruitmentTicketSha256"))
            or type(value.get("recruitmentTicketIssuedAt")) is not int
            or type(value.get("recruitmentTicketExpiresAt")) is not int
            or value["recruitmentTicketExpiresAt"]
            - value["recruitmentTicketIssuedAt"]
            != signed_contract["recruitmentTicketTtlSeconds"]
            or value.get("recruitmentReservationKeySha256")
            != reservation_key_sha256
            or value.get("recruitmentTicketIssuedAt") > consumed_at
            or value.get("recruitmentTicketExpiresAt") <= consumed_at
        ):
            raise GenericStudyServiceError(
                "study_recruitment_contract_changed", 409
            )
        cls._validate_operations_contract(
            signed_contract,
            release,
            participant_binding_sha256,
            participant_binding_key_id,
            participant_binding_key_commitment_sha256,
        )
        return value

    def _validate_signed_challenge(
        self,
        challenge,
        *,
        challenge_id,
        user_id,
        address,
        origin,
        offering_id,
        release,
        now,
        consumed,
        signature,
    ):
        expected_keys = {
            "schema",
            "challengeId",
            "userId",
            "address",
            "origin",
            "action",
            "dataUnionId",
            "offeringId",
            "releaseVersion",
            "releaseSha256",
            "artifactRefs",
            "participantBindingKeyId",
            "participantBindingKeyCommitmentSha256",
            "participantBindingSha256",
            "targetSha256",
            "operations",
            "nonce",
            "issuedAt",
            "expiresAt",
            "consumedAt",
            "message",
        }
        artifact_refs = {
            key: deepcopy(release[key])
            for key in (
                "purpose",
                "survey",
                "participantInformation",
                "protocol",
                "datasetView",
                "activationProfile",
                "taskPlan",
            )
        }
        if isinstance(challenge, dict) and challenge.get("action") == "enroll":
            participant_binding_key_id = self.participant_binding_key_id
            participant_binding_key_commitment_sha256 = (
                _participant_binding_secret_commitment(
                    self.participant_binding_secret,
                    participant_binding_key_id,
                    offering_id,
                    release["releaseSha256"],
                )
            )
            participant_binding_sha256 = _participant_binding(
                self.participant_binding_secret,
                participant_binding_key_id,
                user_id,
                offering_id,
                release["releaseSha256"],
            )
        else:
            participant_binding_key_id = None
            participant_binding_key_commitment_sha256 = None
            participant_binding_sha256 = None
        if (
            not isinstance(challenge, dict)
            or set(challenge) != expected_keys
            or challenge.get("schema")
            != "brainstem.study-offering-action-challenge/v2"
            or challenge.get("challengeId") != challenge_id
            or challenge.get("userId") != user_id
            or challenge.get("address") != address
            or challenge.get("origin") != origin
            or challenge.get("action") not in ACTIONS
            or challenge.get("dataUnionId") != release["dataUnionId"]
            or challenge.get("offeringId") != offering_id
            or challenge.get("releaseVersion") != release["releaseVersion"]
            or challenge.get("releaseSha256") != release["releaseSha256"]
            or challenge.get("artifactRefs") != artifact_refs
            or challenge.get("participantBindingKeyId")
            != participant_binding_key_id
            or challenge.get("participantBindingKeyCommitmentSha256")
            != participant_binding_key_commitment_sha256
            or challenge.get("participantBindingSha256")
            != participant_binding_sha256
            or not isinstance(challenge.get("targetSha256"), str)
            or not _valid_hash(challenge["targetSha256"])
            or not isinstance(challenge.get("nonce"), str)
            or not SESSION_SECRET.fullmatch(challenge["nonce"])
            or type(challenge.get("issuedAt")) is not int
            or type(challenge.get("expiresAt")) is not int
            or challenge["expiresAt"] - challenge["issuedAt"] != CHALLENGE_TTL
        ):
            raise GenericStudyServiceError("challenge_unavailable", 401)
        if challenge["action"] == "enroll":
            self._validate_operations_contract(
                challenge.get("operations"),
                release,
                participant_binding_sha256,
                participant_binding_key_id,
                participant_binding_key_commitment_sha256,
            )
        elif challenge.get("operations") is not None:
            raise GenericStudyServiceError("challenge_unavailable", 401)
        if consumed:
            if (
                type(challenge.get("consumedAt")) is not int
                or challenge["consumedAt"] < challenge["issuedAt"]
                or challenge["consumedAt"] >= challenge["expiresAt"]
            ):
                raise GenericStudyServiceError("challenge_unavailable", 401)
        elif (
            challenge.get("consumedAt") is not None
            or challenge["issuedAt"] > now
            or challenge["expiresAt"] <= now
        ):
            raise GenericStudyServiceError("challenge_unavailable", 401)
        expected_message = _message(origin, address, challenge)
        if not hmac.compare_digest(challenge.get("message", ""), expected_message):
            raise GenericStudyServiceError("challenge_unavailable", 401)
        try:
            verify_wallet_signature(expected_message, signature, address)
        except ParticipantAuthError as error:
            raise GenericStudyServiceError("signature_invalid", 401) from error
        return challenge

    def load_verified_enrollment(
        self,
        user_id,
        offering_id,
        *,
        state=None,
        user=None,
        expected_address=None,
    ):
        if self.operations is None:
            raise GenericStudyServiceError("study_operations_unavailable", 503)
        state = deepcopy(state) if state is not None else self.dao.get_state(user_id)
        private = self._offering_state(state or {}, offering_id)
        enrollment = private.get("enrollment")
        response = private.get("response")
        evidence = private.get("enrollmentEvidence")
        enrollment_fields = {
            "schema",
            "offeringId",
            "releaseVersion",
            "releaseSha256",
            "surveyRevisionSha256",
            "proposalId",
            "permitId",
            "operationStateSha256",
            "taskPlan",
            "participantBindingKeyId",
            "participantBindingKeyCommitmentSha256",
            "participantBindingSha256",
            "recruitmentReservationKeySha256",
            "recruitmentTicketId",
            "recruitmentTicketSha256",
            "recruitmentTicketIssuedAt",
            "recruitmentTicketExpiresAt",
            "state",
            "revision",
            "enrolledAt",
            "startsAt",
            "endsAt",
            "withdrawnAt",
            "renewalRequiredAt",
            "enrollmentSha256",
        }
        if (
            not isinstance(enrollment, dict)
            or set(enrollment) != enrollment_fields
            or enrollment.get("state") != "active"
            or enrollment.get("enrollmentSha256")
            != _enrollment_sha256(enrollment)
            or not isinstance(response, dict)
            or response.get("state") != "active"
            or not isinstance(evidence, dict)
            or set(evidence) != {
                "schema",
                "challenge",
                "signature",
                "signatureSha256",
            }
            or evidence.get("schema") != ENROLLMENT_EVIDENCE_SCHEMA
            or not isinstance(evidence.get("signature"), str)
            or evidence.get("signatureSha256")
            != hashlib.sha256(evidence["signature"].encode("utf-8")).hexdigest()
        ):
            raise GenericStudyServiceError("enrollment_evidence_invalid", 409)
        try:
            validate_response(self.registry, offering_id, response)
            release = self.registry.release(
                offering_id,
                enrollment.get("releaseVersion"),
                enrollment.get("releaseSha256"),
            )
            challenge = evidence["challenge"]
            if user is not None:
                if user.get("_id") != user_id:
                    raise GenericStudyServiceError(
                        "enrollment_evidence_invalid", 409
                    )
                trusted_address = user.get("public_address")
            else:
                trusted_address = expected_address
            if trusted_address is None:
                raise GenericStudyServiceError(
                    "enrollment_evidence_invalid", 409
                )
            address = checksum_address(trusted_address)
            challenge_origin = _origin(challenge.get("origin"))
            self._validate_signed_challenge(
                challenge,
                challenge_id=challenge.get("challengeId"),
                user_id=user_id,
                address=address,
                origin=challenge_origin,
                offering_id=offering_id,
                release=release,
                now=None,
                consumed=True,
                signature=evidence["signature"],
            )
            operations = challenge["operations"]
            reserved = {
                **operations,
                "recruitmentTicketId": enrollment.get("recruitmentTicketId"),
                "recruitmentTicketSha256": enrollment.get(
                    "recruitmentTicketSha256"
                ),
                "recruitmentTicketIssuedAt": enrollment.get(
                    "recruitmentTicketIssuedAt"
                ),
                "recruitmentTicketExpiresAt": enrollment.get(
                    "recruitmentTicketExpiresAt"
                ),
                "recruitmentReservationKeySha256": enrollment.get(
                    "recruitmentReservationKeySha256"
                ),
            }
            self._validate_reserved_contract(
                reserved,
                release,
                enrollment.get("participantBindingSha256"),
                enrollment.get("participantBindingKeyId"),
                enrollment.get("participantBindingKeyCommitmentSha256"),
                operations,
                enrollment.get("recruitmentReservationKeySha256"),
                challenge.get("consumedAt"),
            )
            if (
                challenge["action"] != "enroll"
                or challenge["targetSha256"] != response["revisionSha256"]
                or enrollment.get("surveyRevisionSha256")
                != response["revisionSha256"]
                or response.get("releaseVersion") != release["releaseVersion"]
                or response.get("releaseSha256") != release["releaseSha256"]
                or enrollment.get("participantBindingSha256")
                != challenge["participantBindingSha256"]
                or enrollment.get("participantBindingKeyId")
                != challenge["participantBindingKeyId"]
                or enrollment.get("participantBindingKeyCommitmentSha256")
                != challenge["participantBindingKeyCommitmentSha256"]
                or enrollment.get("proposalId") != operations["proposalId"]
                or enrollment.get("permitId") != operations["permitId"]
                or enrollment.get("operationStateSha256")
                != operations["operationStateSha256"]
                or enrollment.get("taskPlan") != operations["taskPlan"]
                or enrollment.get("recruitmentTicketId")
                != reserved["recruitmentTicketId"]
                or enrollment.get("recruitmentTicketSha256")
                != reserved["recruitmentTicketSha256"]
                or enrollment.get("recruitmentTicketIssuedAt")
                != reserved["recruitmentTicketIssuedAt"]
                or enrollment.get("recruitmentTicketExpiresAt")
                != reserved["recruitmentTicketExpiresAt"]
                or enrollment.get("enrolledAt") != challenge["consumedAt"]
                or enrollment.get("startsAt") != operations["startsAt"]
                or enrollment.get("endsAt") != operations["endsAt"]
            ):
                raise GenericStudyServiceError(
                    "enrollment_evidence_invalid", 409
                )
            ticket = self.operations.load_verified_recruitment_ticket(
                enrollment["proposalId"],
                enrollment["permitId"],
                enrollment["recruitmentTicketId"],
                enrollment["recruitmentTicketSha256"],
                enrollment["participantBindingSha256"],
                enrollment["participantBindingKeyId"],
                enrollment["participantBindingKeyCommitmentSha256"],
                enrollment["enrollmentSha256"],
                enrollment["enrolledAt"],
            )
            if ticket.get("finalized_at") != enrollment["enrolledAt"]:
                raise GenericStudyServiceError(
                    "enrollment_evidence_invalid", 409
                )
        except (
            KeyError,
            UnicodeEncodeError,
            ParticipantAuthError,
            GenericStudyServiceError,
            StudyOperationsError,
            StudyRegistryError,
        ) as error:
            raise GenericStudyServiceError(
                "enrollment_evidence_invalid", 409
            ) from error
        if user is not None:
            if user.get("is_access_blocked"):
                raise GenericStudyServiceError("participant_access_blocked", 409)
            if not has_brainstem_data_consent(user):
                raise GenericStudyServiceError(
                    "current_data_consent_required", 409
                )
        return deepcopy(enrollment)

    def _finalize_recruitment(self, operations, enrollment):
        try:
            self.operations.finalize_recruitment(
                operations["proposalId"],
                operations["recruitmentTicketId"],
                operations["recruitmentTicketSha256"],
                operations["participantBindingSha256"],
                operations["participantBindingKeyId"],
                operations["participantBindingKeyCommitmentSha256"],
                enrollment["enrollmentSha256"],
                enrollment["enrolledAt"],
            )
        except StudyOperationsError as error:
            raise GenericStudyServiceError(error.code, error.status_code) from error

    @staticmethod
    def _enrollment_recruitment_contract(challenge, enrollment):
        return {
            **challenge["operations"],
            "recruitmentTicketId": enrollment["recruitmentTicketId"],
            "recruitmentTicketSha256": enrollment["recruitmentTicketSha256"],
            "recruitmentTicketIssuedAt": enrollment[
                "recruitmentTicketIssuedAt"
            ],
            "recruitmentTicketExpiresAt": enrollment[
                "recruitmentTicketExpiresAt"
            ],
            "recruitmentReservationKeySha256": enrollment[
                "recruitmentReservationKeySha256"
            ],
        }

    def _recover_consumed_enrollment(
        self, user_id, state, challenge, enrollment, user
    ):
        offering_id = challenge.get("offeringId")
        challenge_id = challenge.get("challengeId")
        enrollment_sha256 = enrollment.get("enrollmentSha256")
        evidence = self._offering_state(state, offering_id).get(
            "enrollmentEvidence"
        )
        if (
            challenge.get("action") != "enroll"
            or not isinstance(evidence, dict)
            or evidence.get("challenge") != challenge
            or enrollment_sha256 != _enrollment_sha256(enrollment)
        ):
            raise GenericStudyServiceError(
                "study_recruitment_reconciliation_pending", 503
            )
        operations = self._enrollment_recruitment_contract(
            challenge, enrollment
        )
        try:
            self._finalize_recruitment(operations, enrollment)
            self.load_verified_enrollment(
                user_id,
                offering_id,
                state=state,
                user=user,
            )
        except GenericStudyServiceError as error:
            if error.code in {
                "study_recruitment_ticket_cancelled",
                "study_recruitment_ticket_expired",
                "study_recruitment_state_changed",
                "study_recruitment_ticket_invalid",
            }:
                return self._compensate_failed_enrollment(
                    user_id,
                    offering_id,
                    challenge_id,
                    enrollment_sha256,
                    int(self.clock()),
                )
            raise GenericStudyServiceError(
                "study_recruitment_reconciliation_pending", 503
            ) from error
        try:
            return self._clear_finalized_challenge(
                user_id, challenge_id, enrollment_sha256
            )
        except Exception as error:
            raise GenericStudyServiceError(
                "study_recruitment_reconciliation_pending", 503
            ) from error

    def _clear_finalized_challenge(self, user_id, challenge_id, enrollment_sha256):
        def clear(value):
            challenge = value.get("genericChallenge")
            private = self._offering_state(
                value, challenge.get("offeringId") if isinstance(challenge, dict) else ""
            )
            enrollment = private.get("enrollment")
            if (
                not isinstance(challenge, dict)
                or challenge.get("challengeId") != challenge_id
                or challenge.get("consumedAt") is None
                or not isinstance(enrollment, dict)
                or enrollment.get("enrollmentSha256") != enrollment_sha256
            ):
                raise GenericStudyServiceError(
                    "enrollment_finalization_conflict", 409
                )
            value.pop("genericChallenge", None)
            return value

        return self.dao.mutate_state(user_id, clear)

    def _compensate_failed_enrollment(
        self,
        user_id,
        offering_id,
        challenge_id,
        enrollment_sha256,
        now,
    ):
        def compensate(value):
            challenge = value.get("genericChallenge")
            private = self._offering_state(value, offering_id)
            enrollment = private.get("enrollment")
            evidence = private.get("enrollmentEvidence")
            if (
                not isinstance(challenge, dict)
                or challenge.get("challengeId") != challenge_id
                or challenge.get("consumedAt") is None
                or not isinstance(enrollment, dict)
                or enrollment.get("enrollmentSha256") != enrollment_sha256
                or not isinstance(evidence, dict)
                or evidence.get("challenge") != challenge
            ):
                raise GenericStudyServiceError(
                    "enrollment_finalization_conflict", 409
                )
            tombstone = {
                "schema": "brainstem.study-enrollment-failure-tombstone/v1",
                "offeringId": offering_id,
                "releaseVersion": enrollment.get("releaseVersion"),
                "releaseSha256": enrollment.get("releaseSha256"),
                "proposalId": enrollment.get("proposalId"),
                "permitId": enrollment.get("permitId"),
                "state": "failed",
                "revision": enrollment.get("revision"),
                "enrolledAt": enrollment.get("enrolledAt"),
                "failedAt": now,
                "priorEnrollmentSha256": enrollment_sha256,
            }
            tombstone["enrollmentSha256"] = _enrollment_sha256(tombstone)
            private["enrollment"] = tombstone
            private.pop("enrollmentEvidence", None)
            value.pop("genericChallenge", None)
            return value

        return self.dao.mutate_state(user_id, compensate)

    def catalogue(self):
        return {
            "schema": "brainstem.study-catalogue/v1",
            "offerings": [
                item
                for item in self.registry.catalogue()
                if item["offeringId"] not in MEMBER_ONLY_OFFERINGS
                and (
                    self.available_offerings is None
                    or item["offeringId"] in self.available_offerings
                )
            ],
        }

    @staticmethod
    def _offering_state(state, offering_id):
        return state.get("offerings", {}).get(offering_id, {})

    def _projection(self, offering_id, state):
        private = self._offering_state(state, offering_id)
        current_response = private.get("response")
        if current_response is not None:
            validate_response(self.registry, offering_id, current_response)
        response_history = private.get("responseHistory", [])
        for item in response_history:
            validate_response(self.registry, offering_id, item)
        history = [participant_response(item) for item in response_history]
        enrollment = private.get("enrollment")
        pending = state.get("genericChallenge")
        pending_finalization = (
            isinstance(enrollment, dict)
            and enrollment.get("state") == "active"
            and isinstance(pending, dict)
            and pending.get("action") == "enroll"
            and pending.get("offeringId") == offering_id
            and type(pending.get("consumedAt")) is int
            and pending.get("participantBindingSha256")
            == enrollment.get("participantBindingSha256")
        )
        projected_enrollment = None
        if enrollment:
            projected_enrollment = {
                key: enrollment.get(key)
                for key in (
                    "state",
                    "revision",
                    "releaseVersion",
                    "releaseSha256",
                    "startsAt",
                    "endsAt",
                    "enrolledAt",
                    "withdrawnAt",
                    "renewalRequiredAt",
                    "proposalId",
                    "permitId",
                    "taskPlan",
                )
            }
            if pending_finalization:
                projected_enrollment["state"] = "pending_finalization"
        return {
            "offering": self.registry.public(offering_id),
            "response": participant_response(current_response),
            "enrollment": projected_enrollment,
            "history": history,
        }

    def inbox(self, token, origin):
        user = self._participant(token, origin)
        state = self._state(user["_id"], user)
        return {
            "schema": "brainstem.study-inbox/v1",
            "offerings": [
                self._projection(item["offeringId"], state)
                for item in self.registry.catalogue()
                if (
                    self.available_offerings is None
                    or item["offeringId"] in self.available_offerings
                )
                and (
                    item["offeringId"] not in MEMBER_ONLY_OFFERINGS
                    or (
                        self.offering_access is not None
                        and self.offering_access(item["offeringId"], user)
                    )
                )
            ],
        }

    def status(self, token, origin, offering_id):
        user = self._participant(token, origin)
        self.registry.release(offering_id)
        self._require_offering_access(offering_id, user)
        state = self._state(user["_id"], user)
        return {
            "schema": "brainstem.study-offering-status/v1",
            **self._projection(offering_id, state),
        }

    def tasks(self, token, origin, offering_id):
        user = self._participant(token, origin)
        release = self.registry.release(offering_id)
        if release["offeringType"] != "study":
            raise GenericStudyServiceError("study_tasks_unavailable", 404)
        state = self._state(user["_id"], user)
        enrollment = self.load_verified_enrollment(
            user["_id"], offering_id, state=state, user=user
        )
        try:
            return self.operations.participant_tasks(
                enrollment,
                user["_id"],
                self.task_completion_source,
            )
        except StudyOperationsError as error:
            raise GenericStudyServiceError(error.code, error.status_code) from error

    def _answer(self, offering_id, body, now, previous):
        release = self.registry.release(offering_id)
        if (
            not isinstance(body, dict)
            or set(body) != {"releaseSha256", "surveyVersion", "answers"}
            or body["releaseSha256"] != release["releaseSha256"]
            or body["surveyVersion"] != release["survey"]["version"]
        ):
            raise GenericStudyServiceError("survey_request_invalid")
        try:
            return create_response(
                self.registry,
                offering_id,
                body["answers"],
                submitted_at=now,
                previous=previous,
            )
        except StudyRegistryError as error:
            raise GenericStudyServiceError(str(error), 422) from error

    def challenge(
        self,
        token,
        origin,
        offering_id,
        action,
        answer_body=None,
        release_sha256=None,
    ):
        if action not in ACTIONS:
            raise GenericStudyServiceError("study_action_invalid")
        origin = _origin(origin)
        release = self.registry.release(offering_id)
        user = self._participant(token, origin)
        self._require_offering_access(offering_id, user)
        state = self._state(user["_id"], user)
        replaced_challenge = state.get("genericChallenge") or {}
        replaced_challenge_id = replaced_challenge.get("challengeId")
        if replaced_challenge.get("consumedAt") is not None:
            raise GenericStudyServiceError(
                "enrollment_finalization_pending", 409
            )
        private = self._offering_state(state, offering_id)
        current = private.get("response")
        enrollment = private.get("enrollment")
        now = int(self.clock())
        participant_binding_key_id = None
        participant_binding_key_commitment_sha256 = None
        participant_binding_sha256 = None
        operations = None
        if action == "answer":
            pending_response = self._answer(offering_id, answer_body, now, current)
            target = pending_response["revisionSha256"]
        elif action == "enroll":
            if release["offeringType"] != "study":
                raise GenericStudyServiceError("questionnaire_enrollment_forbidden", 409)
            if not _eligible(offering_id, current):
                raise GenericStudyServiceError("eligible_survey_required", 409)
            if (
                current.get("releaseVersion") != release["releaseVersion"]
                or current.get("releaseSha256") != release["releaseSha256"]
            ):
                raise GenericStudyServiceError("current_release_response_required", 409)
            if enrollment and enrollment.get("state") == "withdrawn":
                raise GenericStudyServiceError("withdrawal_is_terminal", 409)
            if enrollment and enrollment.get("state") == "active":
                raise GenericStudyServiceError("already_enrolled", 409)
            if release_sha256 != release["releaseSha256"]:
                raise GenericStudyServiceError("release_changed", 409)
            if self.operations is None:
                raise GenericStudyServiceError(
                    "study_operations_unavailable", 503
                )
            participant_binding_key_id = self.participant_binding_key_id
            participant_binding_key_commitment_sha256 = (
                _participant_binding_secret_commitment(
                    self.participant_binding_secret,
                    participant_binding_key_id,
                    offering_id,
                    release["releaseSha256"],
                )
            )
            participant_binding_sha256 = _participant_binding(
                self.participant_binding_secret,
                participant_binding_key_id,
                user["_id"],
                offering_id,
                release["releaseSha256"],
            )
            operations = self._recruitment_contract(
                release,
                participant_binding_sha256,
                participant_binding_key_id,
                participant_binding_key_commitment_sha256,
                now,
            )
            target = current["revisionSha256"]
        elif action == "withdraw":
            if (
                not enrollment
                or enrollment.get("state") not in {"active", "renewal_required"}
            ):
                raise GenericStudyServiceError("active_enrollment_required", 409)
            if enrollment.get("enrollmentSha256") != _enrollment_sha256(
                enrollment
            ):
                raise GenericStudyServiceError("enrollment_invalid", 409)
            try:
                release = self.registry.release(
                    offering_id,
                    enrollment.get("releaseVersion"),
                    enrollment.get("releaseSha256"),
                )
            except StudyRegistryError as error:
                raise GenericStudyServiceError(
                    "enrollment_release_unavailable", 409
                ) from error
            if release["offeringType"] != "study":
                raise GenericStudyServiceError("active_enrollment_required", 409)
            target = enrollment["enrollmentSha256"]
        else:
            if not current or current.get("state") == "deleted":
                raise GenericStudyServiceError("survey_revision_unavailable", 409)
            target = current.get("revisionSha256") or content_sha256(current)
        requested_release_sha256 = (
            answer_body.get("releaseSha256")
            if action == "answer" and isinstance(answer_body, dict)
            else release_sha256
        )
        if requested_release_sha256 != release["releaseSha256"]:
            raise GenericStudyServiceError("release_changed", 409)
        artifact_refs = {
            key: deepcopy(release[key])
            for key in (
                "purpose",
                "survey",
                "participantInformation",
                "protocol",
                "datasetView",
                "activationProfile",
                "taskPlan",
            )
        }
        challenge_id = self.id_factory()
        nonce = self.nonce_factory()
        if not IDENTIFIER.fullmatch(challenge_id) or not SESSION_SECRET.fullmatch(nonce):
            raise RuntimeError("invalid generated study challenge")
        challenge = {
            "schema": "brainstem.study-offering-action-challenge/v2",
            "challengeId": challenge_id,
            "userId": user["_id"],
            "address": checksum_address(user["public_address"]),
            "origin": origin,
            "action": action,
            "dataUnionId": release["dataUnionId"],
            "offeringId": offering_id,
            "releaseVersion": release["releaseVersion"],
            "releaseSha256": release["releaseSha256"],
            "artifactRefs": artifact_refs,
            "participantBindingKeyId": participant_binding_key_id,
            "participantBindingKeyCommitmentSha256": (
                participant_binding_key_commitment_sha256
            ),
            "participantBindingSha256": participant_binding_sha256,
            "targetSha256": target,
            "operations": operations,
            "nonce": nonce,
            "issuedAt": now,
            "expiresAt": now + CHALLENGE_TTL,
            "consumedAt": None,
        }
        challenge["message"] = _message(origin, challenge["address"], challenge)

        def update(value):
            value["genericChallenge"] = challenge
            return value

        self.dao.mutate_state(user["_id"], update)
        if replaced_challenge_id:
            self.pending_answers.discard(replaced_challenge_id, now)
        if action == "answer":
            self.pending_answers.put(
                challenge_id, pending_response, challenge["expiresAt"], now
            )
        return {
            "challengeId": challenge_id,
            "message": challenge["message"],
            "expiresAt": challenge["expiresAt"],
            "chainId": CHAIN_ID,
            "method": "personal_sign",
        }

    def apply(
        self,
        token,
        origin,
        offering_id,
        challenge_id,
        signature,
    ):
        origin = _origin(origin)
        user = self._participant(token, origin)
        self._require_offering_access(offering_id, user)
        address = checksum_address(user["public_address"])
        now = int(self.clock())
        state = self._state(user["_id"], user)
        stored_challenge = state.get("genericChallenge") or {}
        if stored_challenge.get("challengeId") != challenge_id:
            raise GenericStudyServiceError("challenge_unavailable", 401)
        if stored_challenge.get("consumedAt") is not None:
            private = self._offering_state(state, offering_id)
            enrollment = private.get("enrollment")
            evidence = private.get("enrollmentEvidence")
            if (
                stored_challenge.get("action") != "enroll"
                or not isinstance(enrollment, dict)
                or not isinstance(evidence, dict)
                or evidence.get("challenge") != stored_challenge
                or not isinstance(evidence.get("signature"), str)
                or not isinstance(signature, str)
                or not hmac.compare_digest(evidence["signature"], signature)
            ):
                raise GenericStudyServiceError("challenge_unavailable", 401)
            try:
                release = self.registry.release(
                    offering_id,
                    enrollment.get("releaseVersion"),
                    enrollment.get("releaseSha256"),
                )
            except StudyRegistryError as error:
                raise GenericStudyServiceError(
                    "enrollment_evidence_invalid", 409
                ) from error
            self._validate_signed_challenge(
                stored_challenge,
                challenge_id=challenge_id,
                user_id=user["_id"],
                address=address,
                origin=origin,
                offering_id=offering_id,
                release=release,
                now=now,
                consumed=True,
                signature=signature,
            )
            if enrollment.get("enrollmentSha256") != _enrollment_sha256(
                enrollment
            ):
                raise GenericStudyServiceError(
                    "enrollment_evidence_invalid", 409
                )
            operations = self._enrollment_recruitment_contract(
                stored_challenge, enrollment
            )
            try:
                self._finalize_recruitment(
                    operations, enrollment
                )
            except GenericStudyServiceError as error:
                if error.code in {
                    "study_recruitment_ticket_cancelled",
                    "study_recruitment_ticket_expired",
                    "study_recruitment_state_changed",
                    "study_recruitment_ticket_invalid",
                }:
                    self._compensate_failed_enrollment(
                        user["_id"],
                        offering_id,
                        challenge_id,
                        enrollment["enrollmentSha256"],
                        now,
                    )
                raise
            state = self._clear_finalized_challenge(
                user["_id"], challenge_id, enrollment["enrollmentSha256"]
            )
            return {
                "schema": "brainstem.study-offering-status/v1",
                **self._projection(offering_id, state),
            }
        if stored_challenge.get("action") == "withdraw":
            enrollment = self._offering_state(state, offering_id).get("enrollment")
            if (
                not isinstance(enrollment, dict)
                or enrollment.get("state")
                not in {"active", "renewal_required"}
            ):
                raise GenericStudyServiceError("active_enrollment_required", 409)
            if enrollment.get("enrollmentSha256") != _enrollment_sha256(
                enrollment
            ):
                raise GenericStudyServiceError("enrollment_invalid", 409)
            try:
                release = self.registry.release(
                    offering_id,
                    enrollment.get("releaseVersion"),
                    enrollment.get("releaseSha256"),
                )
            except StudyRegistryError as error:
                raise GenericStudyServiceError(
                    "enrollment_release_unavailable", 409
                ) from error
        else:
            release = self.registry.release(offering_id)
        pending_response = self.pending_answers.get(challenge_id, now)
        signed_operations = stored_challenge.get("operations")
        if stored_challenge.get("action") == "enroll":
            consumed_at = int(self.clock())
            self._validate_signed_challenge(
                stored_challenge,
                challenge_id=challenge_id,
                user_id=user["_id"],
                address=address,
                origin=origin,
                offering_id=offering_id,
                release=release,
                now=consumed_at,
                consumed=False,
                signature=signature,
            )
            reservation_key_sha256 = _recruitment_reservation_key(challenge_id)
            operations = self._reserve_recruitment(
                release,
                stored_challenge["participantBindingSha256"],
                stored_challenge["participantBindingKeyId"],
                stored_challenge["participantBindingKeyCommitmentSha256"],
                signed_operations,
                reservation_key_sha256,
                consumed_at,
            )
            now = operations["recruitmentTicketIssuedAt"]
            self._validate_signed_challenge(
                stored_challenge,
                challenge_id=challenge_id,
                user_id=user["_id"],
                address=address,
                origin=origin,
                offering_id=offering_id,
                release=release,
                now=now,
                consumed=False,
                signature=signature,
            )
        else:
            self._validate_signed_challenge(
                stored_challenge,
                challenge_id=challenge_id,
                user_id=user["_id"],
                address=address,
                origin=origin,
                offering_id=offering_id,
                release=release,
                now=now,
                consumed=False,
                signature=signature,
            )
            operations = None

        def update(state):
            challenge = state.get("genericChallenge")
            self._validate_signed_challenge(
                challenge,
                challenge_id=challenge_id,
                user_id=user["_id"],
                address=address,
                origin=origin,
                offering_id=offering_id,
                release=release,
                now=now,
                consumed=False,
                signature=signature,
            )
            offerings = state.setdefault("offerings", {})
            private = offerings.setdefault(offering_id, {})
            current = private.get("response")
            enrollment = private.get("enrollment")
            action = challenge["action"]
            record_receipt = True
            if action == "answer":
                response = pending_response
                if response is None:
                    raise GenericStudyServiceError("challenge_unavailable", 401)
                validate_response(self.registry, offering_id, response)
                if response["revisionSha256"] != challenge["targetSha256"]:
                    raise GenericStudyServiceError("challenge_contract_changed", 409)
                changed = current is None or response["revisionSha256"] != current.get(
                    "revisionSha256"
                )
                if current is not None and changed:
                    history = private.setdefault("responseHistory", [])
                    if len(history) >= MAX_HISTORY:
                        raise GenericStudyServiceError("survey_history_limit", 409)
                    history.append(_superseded(current))
                    if enrollment and enrollment.get("state") == "active":
                        enrollment = deepcopy(enrollment)
                        enrollment["state"] = "renewal_required"
                        enrollment["renewalRequiredAt"] = now
                        enrollment["enrollmentSha256"] = _enrollment_sha256(
                            enrollment
                        )
                        private["enrollment"] = enrollment
                        block_recurring_for_renewal(private)
                if changed:
                    private["response"] = response
                else:
                    record_receipt = False
            elif action == "enroll":
                if release["offeringType"] != "study" or not _eligible(offering_id, current):
                    raise GenericStudyServiceError("eligible_survey_required", 409)
                if (
                    current.get("releaseVersion") != release["releaseVersion"]
                    or current.get("releaseSha256") != release["releaseSha256"]
                ):
                    raise GenericStudyServiceError(
                        "current_release_response_required", 409
                    )
                if current["revisionSha256"] != challenge["targetSha256"]:
                    raise GenericStudyServiceError("challenge_contract_changed", 409)
                if not has_brainstem_data_consent(user):
                    raise GenericStudyServiceError("current_data_consent_required", 409)
                if enrollment and enrollment.get("state") == "withdrawn":
                    raise GenericStudyServiceError("withdrawal_is_terminal", 409)
                if enrollment and enrollment.get("state") == "active":
                    raise GenericStudyServiceError("already_enrolled", 409)
                if not enrollment or enrollment.get("state") in {
                    "renewal_required",
                    "failed",
                }:
                    revision = (enrollment or {}).get("revision", 0) + 1
                    enrollment = {
                        "schema": "brainstem.study-offering-enrollment/v1",
                        "offeringId": offering_id,
                        "releaseVersion": release["releaseVersion"],
                        "releaseSha256": release["releaseSha256"],
                        "surveyRevisionSha256": current["revisionSha256"],
                        "proposalId": operations["proposalId"],
                        "permitId": operations["permitId"],
                        "operationStateSha256": operations[
                            "operationStateSha256"
                        ],
                        "taskPlan": deepcopy(operations["taskPlan"]),
                        "participantBindingKeyId": operations[
                            "participantBindingKeyId"
                        ],
                        "participantBindingKeyCommitmentSha256": operations[
                            "participantBindingKeyCommitmentSha256"
                        ],
                        "participantBindingSha256": operations[
                            "participantBindingSha256"
                        ],
                        "recruitmentReservationKeySha256": operations[
                            "recruitmentReservationKeySha256"
                        ],
                        "recruitmentTicketId": operations[
                            "recruitmentTicketId"
                        ],
                        "recruitmentTicketSha256": operations[
                            "recruitmentTicketSha256"
                        ],
                        "recruitmentTicketIssuedAt": operations[
                            "recruitmentTicketIssuedAt"
                        ],
                        "recruitmentTicketExpiresAt": operations[
                            "recruitmentTicketExpiresAt"
                        ],
                        "state": "active",
                        "revision": revision,
                        "enrolledAt": now,
                        "startsAt": operations["startsAt"],
                        "endsAt": operations["endsAt"],
                        "withdrawnAt": None,
                        "renewalRequiredAt": None,
                    }
                    enrollment["enrollmentSha256"] = _enrollment_sha256(enrollment)
                    private["enrollment"] = enrollment
                    evidence_challenge = deepcopy(challenge)
                    evidence_challenge["consumedAt"] = now
                    private["enrollmentEvidence"] = {
                        "schema": ENROLLMENT_EVIDENCE_SCHEMA,
                        "challenge": evidence_challenge,
                        "signature": signature,
                        "signatureSha256": hashlib.sha256(
                            signature.encode("utf-8")
                        ).hexdigest(),
                    }
            elif action == "withdraw":
                if (
                    not enrollment
                    or enrollment.get("state")
                    not in {"active", "renewal_required"}
                ):
                    raise GenericStudyServiceError("active_enrollment_required", 409)
                if enrollment.get("enrollmentSha256") != _enrollment_sha256(
                    enrollment
                ):
                    raise GenericStudyServiceError("enrollment_invalid", 409)
                if (
                    enrollment.get("releaseVersion") != release["releaseVersion"]
                    or enrollment.get("releaseSha256")
                    != release["releaseSha256"]
                ):
                    raise GenericStudyServiceError(
                        "enrollment_release_unavailable", 409
                    )
                if enrollment["enrollmentSha256"] != challenge["targetSha256"]:
                    raise GenericStudyServiceError("challenge_contract_changed", 409)
                enrollment = deepcopy(enrollment)
                enrollment["state"] = "withdrawn"
                enrollment["withdrawnAt"] = now
                enrollment["enrollmentSha256"] = _enrollment_sha256(enrollment)
                private["enrollment"] = enrollment
                scrub_recurring(private, state="revoked", now=now)
            elif action == "delete":
                if not current or current.get("state") == "deleted":
                    raise GenericStudyServiceError("survey_revision_unavailable", 409)
                target = current.get("revisionSha256") or content_sha256(current)
                if target != challenge["targetSha256"]:
                    raise GenericStudyServiceError("challenge_contract_changed", 409)
                history = private.setdefault("responseHistory", [])
                private["responseHistory"] = [
                    _deleted(item, now) for item in history
                ]
                private["response"] = _deleted(current, now)
                if enrollment:
                    enrollment = {
                        "schema": "brainstem.study-enrollment-deletion-tombstone/v2",
                        "offeringId": offering_id,
                        "state": "withdrawn",
                        "revision": enrollment.get("revision"),
                        "deletedOn": time.strftime(
                            "%Y-%m-%d", time.gmtime(now)
                        ),
                    }
                    enrollment["enrollmentSha256"] = _enrollment_sha256(
                        enrollment
                    )
                    private["enrollment"] = enrollment
                private.pop("enrollmentEvidence", None)
                scrub_recurring(private, state="deleted", now=now)
                record_receipt = False
            else:
                raise GenericStudyServiceError("study_action_invalid")
            action_history = state.setdefault("genericActionHistory", [])
            if not isinstance(action_history, list):
                action_history = []
                state["genericActionHistory"] = action_history
            if action == "delete":
                action_history[:] = [
                    receipt
                    for receipt in action_history
                    if not isinstance(receipt, dict)
                    or receipt.get("offeringId") != offering_id
                ]
            if record_receipt:
                action_history.append(
                    {
                        "schema": "brainstem.study-offering-action-receipt/v1",
                        "offeringId": offering_id,
                        "releaseSha256": release["releaseSha256"],
                        "action": action,
                        "occurredAt": now,
                    }
                )
            del action_history[:-MAX_ACTION_HISTORY]
            if action == "enroll":
                state["genericChallenge"] = evidence_challenge
            else:
                state.pop("genericChallenge", None)
            return state

        state = self.dao.mutate_state(user["_id"], update)
        self.pending_answers.discard(challenge_id, now)
        if stored_challenge.get("action") == "enroll":
            enrollment = self._offering_state(state, offering_id)["enrollment"]
            try:
                self._finalize_recruitment(operations, enrollment)
            except GenericStudyServiceError as error:
                if error.code in {
                    "study_recruitment_ticket_cancelled",
                    "study_recruitment_ticket_expired",
                    "study_recruitment_state_changed",
                    "study_recruitment_ticket_invalid",
                }:
                    self._compensate_failed_enrollment(
                        user["_id"],
                        offering_id,
                        challenge_id,
                        enrollment["enrollmentSha256"],
                        now,
                    )
                raise
            state = self._clear_finalized_challenge(
                user["_id"], challenge_id, enrollment["enrollmentSha256"]
            )
        return {
            "schema": "brainstem.study-offering-status/v1",
            **self._projection(offering_id, state),
        }
