"""Single owner for signed study lifecycle, amendments, tasks, and projections."""

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import hmac
import re
import secrets
import time
import uuid
from urllib.parse import urlparse

from commands.dataunions.brainstem.study_activation import (
    PERMIT_ID,
    StudyActivationError,
    release_binding,
)
from commands.dataunions.brainstem.study_proposals import (
    SHA256,
    StudyProposalError,
    normalize_proposal_id,
)
from commands.dataunions.studies.registry import StudyRegistryError, content_sha256
from commands.users.participant_auth import (
    ParticipantAuthError,
    checksum_address,
    rfc3339,
    validate_origin,
    verify_wallet_signature,
)
from dao.study_operations_dao import StudyOperationsStateError


CHALLENGE_ID = re.compile(r"^[0-9a-f]{32}$")
RECRUITMENT_TICKET_ID = CHALLENGE_ID
EVENT_ID = re.compile(r"^operation_[0-9a-f]{32}$")
NONCE = re.compile(r"^[A-Za-z0-9_-]{16,128}$")
IDEMPOTENCY_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{7,127}$")
REASON_CODE = re.compile(r"^[a-z0-9][a-z0-9._-]{2,63}$")
PURPOSE = "brainstem.study.operator-transition"
MIN_CHALLENGE_TTL = 60
MAX_CHALLENGE_TTL = 600
LIFECYCLE_ACTIONS = {
    ("permitted", "recruit"): "recruiting",
    ("recruiting", "activate"): "active",
    ("active", "pause"): "paused",
    ("paused", "resume"): "active",
    ("active", "close"): "closed",
    ("paused", "close"): "closed",
    ("closed", "archive"): "archived",
}
SPECIAL_ACTIONS = {"revoke", "correct", "supersede"}
ALL_ACTIONS = {action for _state, action in LIFECYCLE_ACTIONS} | SPECIAL_ACTIONS
RENEWAL_BINDINGS = (
    "purpose",
    "survey",
    "participantInformation",
    "protocol",
    "taskPlan",
    "datasetView",
    "activationProfile",
)
PRIVACY_METRICS = (
    "recruitment",
    "adherence",
    "dataQuality",
    "resultAvailability",
)
MAX_METRIC_STATES = 10000


class StudyOperationsError(RuntimeError):
    def __init__(self, code, status_code=400):
        super().__init__(code)
        self.code = code
        self.status_code = status_code


def state_sha256(value):
    return content_sha256(
        {key: item for key, item in value.items() if key != "stateSha256"}
    )


def _event_sha256(value):
    return content_sha256(
        {key: item for key, item in value.items() if key != "eventSha256"}
    )


def _ticket_sha256(value):
    immutable = {
        key: value[key]
        for key in (
            "schema",
            "ticket_id",
            "proposal_id",
            "permit_id",
            "participant_binding_key_id",
            "participant_binding_key_commitment_sha256",
            "participant_binding_sha256",
            "reservation_key_sha256",
            "operation_state_sha256",
            "release_sha256",
            "task_plan_sha256",
            "issued_at",
            "expires_at",
        )
    }
    return content_sha256(immutable)


def _validate_recruitment_ticket(value):
    expected = {
        "schema",
        "ticket_id",
        "proposal_id",
        "permit_id",
        "participant_binding_key_id",
        "participant_binding_key_commitment_sha256",
        "participant_binding_sha256",
        "reservation_key_sha256",
        "operation_state_sha256",
        "release_sha256",
        "task_plan_sha256",
        "issued_at",
        "expires_at",
        "ticket_sha256",
        "finalized_at",
        "enrollment_sha256",
        "cancelled_at",
    }
    try:
        proposal_id = normalize_proposal_id(value.get("proposal_id"))
    except (AttributeError, StudyProposalError):
        proposal_id = None
    if (
        not isinstance(value, dict)
        or set(value) != expected
        or value.get("schema") != "brainstem.study-recruitment-ticket/v3"
        or not isinstance(value.get("ticket_id"), str)
        or not RECRUITMENT_TICKET_ID.fullmatch(value["ticket_id"])
        or proposal_id != value.get("proposal_id")
        or not isinstance(value.get("permit_id"), str)
        or not PERMIT_ID.fullmatch(value["permit_id"])
        or not isinstance(value.get("participant_binding_key_id"), str)
        or not 1 <= len(value["participant_binding_key_id"]) <= 64
        or not value["participant_binding_key_id"].isascii()
        or not all(
            character.isalnum() or character in "._-"
            for character in value["participant_binding_key_id"]
        )
        or not isinstance(
            value.get("participant_binding_key_commitment_sha256"), str
        )
        or not SHA256.fullmatch(
            value["participant_binding_key_commitment_sha256"]
        )
        or not isinstance(value.get("participant_binding_sha256"), str)
        or not SHA256.fullmatch(value["participant_binding_sha256"])
        or not isinstance(value.get("reservation_key_sha256"), str)
        or not SHA256.fullmatch(value["reservation_key_sha256"])
        or not isinstance(value.get("operation_state_sha256"), str)
        or not SHA256.fullmatch(value["operation_state_sha256"])
        or not isinstance(value.get("release_sha256"), str)
        or not SHA256.fullmatch(value["release_sha256"])
        or not isinstance(value.get("task_plan_sha256"), str)
        or not SHA256.fullmatch(value["task_plan_sha256"])
        or type(value.get("issued_at")) is not int
        or type(value.get("expires_at")) is not int
        or value["expires_at"] <= value["issued_at"]
        or value["expires_at"] - value["issued_at"] < MIN_CHALLENGE_TTL
        or value["expires_at"] - value["issued_at"] > MAX_CHALLENGE_TTL
        or value.get("ticket_sha256") != _ticket_sha256(value)
        or (
            value.get("finalized_at") is not None
            and (
                type(value["finalized_at"]) is not int
                or not value["issued_at"]
                <= value["finalized_at"]
                < value["expires_at"]
            )
        )
        or (
            value.get("enrollment_sha256") is not None
            and (
                not isinstance(value["enrollment_sha256"], str)
                or not SHA256.fullmatch(value["enrollment_sha256"])
            )
        )
        or (value.get("finalized_at") is None)
        != (value.get("enrollment_sha256") is None)
        or (
            value.get("cancelled_at") is not None
            and (
                type(value["cancelled_at"]) is not int
                or value["cancelled_at"] < value["issued_at"]
            )
        )
        or (
            value.get("finalized_at") is not None
            and value.get("cancelled_at") is not None
        )
    ):
        raise StudyOperationsError("study_recruitment_ticket_invalid", 409)
    return value


def _text_sha256(value):
    if not isinstance(value, str):
        raise StudyOperationsError("study_operation_evidence_invalid", 409)
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def validate_operation_event(value):
    expected = {
        "schema",
        "eventId",
        "challengeId",
        "proposalId",
        "permitId",
        "action",
        "idempotencyKey",
        "operatorId",
        "priorStateSha256",
        "targetLifecycleState",
        "bundleSha256",
        "details",
        "occurredAt",
        "signedMessageSha256",
        "operatorSignatureSha256",
        "eventSha256",
    }
    if (
        not isinstance(value, dict)
        or set(value) != expected
        or value.get("schema") != "brainstem.study-operation-event/v1"
        or not isinstance(value.get("eventId"), str)
        or not EVENT_ID.fullmatch(value["eventId"])
        or not isinstance(value.get("challengeId"), str)
        or not CHALLENGE_ID.fullmatch(value["challengeId"])
        or value.get("eventId") != "operation_{}".format(value["challengeId"])
        or value.get("action") not in ALL_ACTIONS
        or not isinstance(value.get("idempotencyKey"), str)
        or not IDEMPOTENCY_KEY.fullmatch(value["idempotencyKey"])
        or not isinstance(value.get("priorStateSha256"), str)
        or not SHA256.fullmatch(value["priorStateSha256"])
        or not isinstance(value.get("bundleSha256"), str)
        or not SHA256.fullmatch(value["bundleSha256"])
        or not isinstance(value.get("signedMessageSha256"), str)
        or not SHA256.fullmatch(value["signedMessageSha256"])
        or not isinstance(value.get("operatorSignatureSha256"), str)
        or not SHA256.fullmatch(value["operatorSignatureSha256"])
        or not isinstance(value.get("eventSha256"), str)
        or not SHA256.fullmatch(value["eventSha256"])
        or value["eventSha256"] != _event_sha256(value)
    ):
        raise StudyOperationsError("study_operation_event_invalid", 409)
    _parse_rfc3339(value.get("occurredAt"))
    return value


def validate_operations_state(value):
    expected = {
        "schema",
        "proposalId",
        "permitId",
        "permitSha256",
        "offeringId",
        "releaseVersion",
        "releaseSha256",
        "taskPlan",
        "lifecycleState",
        "disposition",
        "supersededBy",
        "eventCount",
        "lastEventSha256",
        "updatedAt",
        "stateSha256",
    }
    if (
        not isinstance(value, dict)
        or set(value) != expected
        or value.get("schema") != "brainstem.study-operations-state/v1"
        or value.get("lifecycleState")
        not in {"permitted", "recruiting", "active", "paused", "closed", "archived"}
        or value.get("disposition") not in {"current", "revoked", "superseded"}
        or (value["disposition"] == "superseded")
        != isinstance(value.get("supersededBy"), dict)
        or type(value.get("eventCount")) is not int
        or value["eventCount"] < 0
        or not isinstance(value.get("stateSha256"), str)
        or not SHA256.fullmatch(value["stateSha256"])
        or value["stateSha256"] != state_sha256(value)
    ):
        raise StudyOperationsError("study_operations_state_invalid", 409)
    if value["eventCount"] == 0:
        if value["lastEventSha256"] is not None:
            raise StudyOperationsError("study_operations_state_invalid", 409)
    elif (
        not isinstance(value["lastEventSha256"], str)
        or not SHA256.fullmatch(value["lastEventSha256"])
    ):
        raise StudyOperationsError("study_operations_state_invalid", 409)
    if not isinstance(value.get("taskPlan"), dict):
        raise StudyOperationsError("study_operations_state_invalid", 409)
    return value


def classify_amendment(previous_release, replacement_release):
    if (
        previous_release.get("offeringType") != "study"
        or replacement_release.get("offeringType") != "study"
        or previous_release.get("dataUnionId") != replacement_release.get("dataUnionId")
        or previous_release.get("offeringId") != replacement_release.get("offeringId")
        or previous_release.get("releaseSha256")
        == replacement_release.get("releaseSha256")
    ):
        raise StudyOperationsError("study_supersession_invalid", 409)
    changed = [
        field
        for field in RENEWAL_BINDINGS
        if previous_release.get(field) != replacement_release.get(field)
    ]
    return {
        "schema": "brainstem.study-amendment-classification/v1",
        "renewalRequired": bool(changed),
        "changedBindings": changed,
    }


def task_window(task_plan, now):
    if type(now) is not int:
        raise StudyOperationsError("study_task_time_invalid")
    current = datetime.fromtimestamp(now, timezone.utc)
    boundary = current.replace(hour=0, minute=0, second=0, microsecond=0)
    if current != boundary:
        boundary = datetime.fromtimestamp(boundary.timestamp() + 86400, timezone.utc)
    duration_days = max(task["windowEndDay"] for task in task_plan["content"]["tasks"])
    start = int(boundary.timestamp())
    return start, start + duration_days * 86400


def privacy_band(value):
    if type(value) is not int or value < 0:
        raise StudyOperationsError("study_privacy_metrics_invalid", 503)
    if value == 0:
        return "none"
    if value < 20:
        return "under_disclosure_floor"
    if value < 50:
        return "20_49"
    if value < 100:
        return "50_99"
    return "100_plus"


def _validate_privacy_snapshot(value, published_on=None):
    allowed_bands = {
        "none",
        "under_disclosure_floor",
        "20_49",
        "50_99",
        "100_plus",
    }
    if (
        not isinstance(value, dict)
        or set(value)
        != {"schema", "publishedOn", "stateSha256", "bands"}
        or value.get("schema") != "brainstem.study-privacy-snapshot/v1"
        or (published_on is not None and value.get("publishedOn") != published_on)
        or not isinstance(value.get("stateSha256"), str)
        or not SHA256.fullmatch(value["stateSha256"])
        or not isinstance(value.get("bands"), dict)
        or set(value["bands"]) != set(PRIVACY_METRICS)
        or any(item not in allowed_bands for item in value["bands"].values())
    ):
        raise StudyOperationsError("study_privacy_snapshot_invalid", 503)
    try:
        datetime.strptime(value["publishedOn"], "%Y-%m-%d")
    except (TypeError, ValueError) as error:
        raise StudyOperationsError(
            "study_privacy_snapshot_invalid", 503
        ) from error
    return value


class EmptyTaskCompletionSource:
    """Fail-closed production seam until a reviewed source adapter is supplied."""

    @staticmethod
    def completions(_participant_id, _enrollment):
        return []


class StudyOperationsMetricsSource:
    """Aggregate only source-verified enrollment authority, returning no rows."""

    def __init__(self, study_dao, enrollment_verifier=None):
        self.study_dao = study_dao
        self.enrollment_verifier = enrollment_verifier

    def counts(self, operations_state):
        if not isinstance(operations_state, dict):
            raise StudyOperationsError("study_privacy_metrics_invalid", 503)
        if not callable(self.enrollment_verifier):
            raise StudyOperationsError("study_privacy_metrics_unavailable", 503)
        rows = self.study_dao.generic_operations_metric_states(
            MAX_METRIC_STATES + 1
        )
        if len(rows) > MAX_METRIC_STATES:
            raise StudyOperationsError("study_privacy_metrics_capacity", 503)
        recruitment = 0
        for row in rows:
            if not isinstance(row, dict) or not isinstance(
                row.get("user_id"), str
            ):
                continue
            enrollment = self.enrollment_verifier(
                row["user_id"], operations_state["offeringId"], deepcopy(row)
            )
            if (
                isinstance(enrollment, dict)
                and enrollment.get("state") == "active"
                and enrollment.get("proposalId")
                == operations_state["proposalId"]
                and enrollment.get("permitId") == operations_state["permitId"]
                and enrollment.get("offeringId")
                == operations_state["offeringId"]
                and enrollment.get("releaseSha256")
                == operations_state["releaseSha256"]
            ):
                recruitment += 1
        return {
            "recruitment": recruitment,
            "adherence": 0,
            "dataQuality": 0,
            "resultAvailability": 0,
        }


def _initial_state(permit):
    release = permit["bundle"]["release"]
    value = {
        "schema": "brainstem.study-operations-state/v1",
        "proposalId": permit["proposalId"],
        "permitId": permit["permitId"],
        "permitSha256": permit["permitSha256"],
        "offeringId": release["offeringId"],
        "releaseVersion": release["releaseVersion"],
        "releaseSha256": release["releaseSha256"],
        "taskPlan": deepcopy(release["artifacts"]["taskPlan"]),
        "lifecycleState": "permitted",
        "disposition": "current",
        "supersededBy": None,
        "eventCount": 0,
        "lastEventSha256": None,
        "updatedAt": permit["permittedAt"],
    }
    value["stateSha256"] = state_sha256(value)
    return value


def _parse_rfc3339(value):
    if not isinstance(value, str) or not value.endswith("Z"):
        raise StudyOperationsError("study_permit_invalid", 409)
    try:
        timestamp = int(datetime.fromisoformat(value[:-1] + "+00:00").timestamp())
    except ValueError as error:
        raise StudyOperationsError("study_permit_invalid", 409) from error
    if rfc3339(timestamp) != value:
        raise StudyOperationsError("study_permit_invalid", 409)
    return timestamp


def _validate_details(action, details):
    if not isinstance(details, dict):
        raise StudyOperationsError("study_operation_details_invalid")
    if action in {item[1] for item in LIFECYCLE_ACTIONS}:
        if details:
            raise StudyOperationsError("study_operation_details_invalid")
        return {}
    if action == "revoke":
        if set(details) != {"reasonCode", "evidenceSha256"}:
            raise StudyOperationsError("study_operation_details_invalid")
    elif action == "correct":
        if set(details) != {"targetEventSha256", "reasonCode", "evidenceSha256"}:
            raise StudyOperationsError("study_operation_details_invalid")
        if (
            not isinstance(details["targetEventSha256"], str)
            or not SHA256.fullmatch(details["targetEventSha256"])
        ):
            raise StudyOperationsError("study_operation_details_invalid")
    elif action == "supersede":
        if set(details) != {"replacementProposalId", "replacementPermitId"}:
            raise StudyOperationsError("study_operation_details_invalid")
        normalize_proposal_id(details["replacementProposalId"])
        if (
            not isinstance(details["replacementPermitId"], str)
            or not PERMIT_ID.fullmatch(details["replacementPermitId"])
        ):
            raise StudyOperationsError("study_operation_details_invalid")
        return deepcopy(details)
    else:
        raise StudyOperationsError("study_operation_action_invalid")
    if (
        not isinstance(details["reasonCode"], str)
        or not REASON_CODE.fullmatch(details["reasonCode"])
        or not isinstance(details["evidenceSha256"], str)
        or not SHA256.fullmatch(details["evidenceSha256"])
    ):
        raise StudyOperationsError("study_operation_details_invalid")
    return deepcopy(details)


def _message(origin, operator, chain_id, challenge):
    bundle = challenge["bundle"]
    return "\n".join(
        [
            "{} requests a Brainstem study operations signature from:".format(
                urlparse(origin).netloc
            ),
            operator,
            "",
            (
                "Authorize one append-only study operation. This does not answer, "
                "enroll, access participant rows, run compute, or make a payment."
            ),
            "",
            "URI: {}/studies/operator/operations".format(origin),
            "Version: 1",
            "Chain ID: {}".format(chain_id),
            "Nonce: {}".format(challenge["nonce"]),
            "Issued At: {}".format(rfc3339(challenge["issued_at"])),
            "Expiration Time: {}".format(rfc3339(challenge["expires_at"])),
            "Request ID: {}".format(challenge["challenge_id"]),
            "Purpose: {}".format(PURPOSE),
            "Proposal: {}".format(bundle["proposalId"]),
            "Permit: {}".format(bundle["permitId"]),
            "Permit SHA256: {}".format(bundle["permitSha256"]),
            "Action: {}".format(bundle["action"]),
            "Idempotency Key: {}".format(bundle["idempotencyKey"]),
            "Prior State SHA256: {}".format(bundle["priorStateSha256"]),
            "Target Lifecycle State: {}".format(bundle["targetLifecycleState"]),
            "Release SHA256: {}".format(bundle["releaseSha256"]),
            "Task Plan SHA256: {}".format(bundle["taskPlanSha256"]),
            "Details SHA256: {}".format(content_sha256(bundle["details"])),
            "Operation Bundle SHA256: {}".format(bundle["bundleSha256"]),
        ]
    )


class StudyOperationsService:
    def __init__(
        self,
        operations_dao,
        activation_service,
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
        self.operations_dao = operations_dao
        self.activation_service = activation_service
        self.registry = registry
        try:
            self.allowed_operators = frozenset(
                checksum_address(item).lower() for item in allowed_operators
            )
        except ParticipantAuthError as error:
            raise StudyOperationsError("study_operator_configuration_invalid", 503) from error
        self.allowed_origins = tuple(item.rstrip("/") for item in allowed_origins)
        self.chain_id = int(chain_id)
        self.challenge_ttl = int(challenge_ttl)
        self.clock = clock
        self.nonce_factory = nonce_factory
        self.id_factory = id_factory
        if (
            not self.allowed_operators
            or not self.allowed_origins
            or self.chain_id < 1
            or not MIN_CHALLENGE_TTL
            <= self.challenge_ttl
            <= MAX_CHALLENGE_TTL
        ):
            raise StudyOperationsError("study_operator_configuration_invalid", 503)

    def _operator(self, value):
        try:
            operator = checksum_address(value).lower()
        except ParticipantAuthError as error:
            raise StudyOperationsError("study_operator_forbidden", 403) from error
        if operator not in self.allowed_operators:
            raise StudyOperationsError("study_operator_forbidden", 403)
        return operator

    def _origin(self, value):
        try:
            return validate_origin(value, self.allowed_origins)
        except ParticipantAuthError as error:
            raise StudyOperationsError("study_operator_origin_forbidden", 403) from error

    def _permit(self, proposal_id, permit_id):
        if not isinstance(permit_id, str) or not PERMIT_ID.fullmatch(permit_id):
            raise StudyOperationsError("study_permit_invalid", 409)
        try:
            permit = self.activation_service.load_verified_permit(
                proposal_id, permit_id
            )
        except (
            StudyActivationError,
            StudyRegistryError,
        ) as error:
            raise StudyOperationsError("study_permit_invalid", 409) from error
        release_ref = permit["bundle"]["release"]
        try:
            release = self.registry.release(
                release_ref["offeringId"],
                release_ref["releaseVersion"],
                release_ref["releaseSha256"],
            )
            task_plan = self.registry.task_plan(
                release["offeringId"],
                release["releaseVersion"],
                release["releaseSha256"],
            )
        except (KeyError, StudyRegistryError) as error:
            raise StudyOperationsError("study_permit_release_invalid", 409) from error
        if release_binding(release) != release_ref:
            raise StudyOperationsError("study_permit_release_invalid", 409)
        return permit, release, task_plan

    def _state(self, proposal_id, permit_id, persist=False):
        permit, release, task_plan = self._permit(proposal_id, permit_id)
        initial = _initial_state(permit)
        if persist:
            self.operations_dao.ensure_state(proposal_id, initial)
        try:
            verified = self.load_verified_status(proposal_id, permit_id)
            state = verified["state"]
        except StudyOperationsStateError:
            state = initial
        return state, permit, release, task_plan

    @staticmethod
    def _event_input_details(event):
        details = event["details"]
        allowed = {
            "reasonCode",
            "evidenceSha256",
            "targetEventSha256",
            "replacementProposalId",
            "replacementPermitId",
        }
        return {key: value for key, value in details.items() if key in allowed}

    def _verify_event_evidence(self, proposal_id, prior, event, challenge):
        validate_operation_event(event)
        operator = self._operator(event["operatorId"])
        expected_challenge_fields = {
            "schema",
            "challenge_id",
            "proposal_id",
            "permit_id",
            "operator_id",
            "origin",
            "chain_id",
            "purpose",
            "nonce",
            "issued_at",
            "expires_at",
            "bundle",
            "bundle_sha256",
            "idempotency_key",
            "consumed_at",
            "message",
            "event_sha256",
            "signature_sha256",
            "signature",
        }
        if (
            not isinstance(challenge, dict)
            or set(challenge) != expected_challenge_fields
            or challenge.get("schema") != "brainstem.study-operation-challenge/v1"
            or challenge.get("challenge_id") != event["challengeId"]
            or challenge.get("proposal_id") != proposal_id
            or challenge.get("permit_id") != event["permitId"]
            or challenge.get("operator_id") != operator
            or challenge.get("chain_id") != self.chain_id
            or challenge.get("purpose") != PURPOSE
            or challenge.get("idempotency_key") != event["idempotencyKey"]
            or challenge.get("event_sha256") != event["eventSha256"]
            or type(challenge.get("issued_at")) is not int
            or type(challenge.get("expires_at")) is not int
            or type(challenge.get("consumed_at")) is not int
            or challenge["expires_at"] <= challenge["issued_at"]
            or challenge["consumed_at"] < challenge["issued_at"]
            or challenge["consumed_at"] > challenge["expires_at"]
            or _parse_rfc3339(event["occurredAt"]) != challenge["consumed_at"]
            or not isinstance(challenge.get("nonce"), str)
            or not NONCE.fullmatch(challenge["nonce"])
        ):
            raise StudyOperationsError("study_operation_evidence_invalid", 409)
        origin = self._origin(challenge.get("origin"))
        bundle = self._bundle(
            proposal_id,
            event["permitId"],
            event["action"],
            event["idempotencyKey"],
            prior,
            self._event_input_details(event),
        )
        expected_message = _message(
            origin,
            operator,
            challenge["chain_id"],
            {**challenge, "bundle": bundle},
        )
        signature_sha256 = _text_sha256(challenge.get("signature"))
        if (
            event["priorStateSha256"] != prior["stateSha256"]
            or event["targetLifecycleState"] != bundle["targetLifecycleState"]
            or event["details"] != bundle["details"]
            or event["bundleSha256"] != bundle["bundleSha256"]
            or challenge.get("bundle") != bundle
            or challenge.get("bundle_sha256") != bundle["bundleSha256"]
            or challenge.get("message") != expected_message
            or event["signedMessageSha256"] != _text_sha256(expected_message)
            or event["operatorSignatureSha256"] != signature_sha256
            or challenge.get("signature_sha256") != signature_sha256
        ):
            raise StudyOperationsError("study_operation_evidence_invalid", 409)
        try:
            verify_wallet_signature(
                expected_message, challenge["signature"], operator
            )
        except ParticipantAuthError as error:
            raise StudyOperationsError("study_operation_evidence_invalid", 409) from error

    def load_verified_status(self, proposal_id, permit_id):
        proposal_id = normalize_proposal_id(proposal_id)
        permit, release, _task_plan = self._permit(proposal_id, permit_id)
        initial = _initial_state(permit)
        try:
            document = self.operations_dao.get_document(proposal_id)
        except StudyOperationsStateError:
            return {
                "schema": "brainstem.study-operations-status/v1",
                "state": initial,
                "events": [],
            }
        events = document.get("events")
        challenges = document.get("challenges")
        stored_state = document.get("state")
        if not isinstance(events, list) or not isinstance(challenges, dict):
            raise StudyOperationsError("study_operations_state_invalid", 409)
        current = initial
        seen_ids = set()
        seen_keys = set()
        previous_time = _parse_rfc3339(initial["updatedAt"])
        for event in events:
            validate_operation_event(event)
            if (
                event.get("eventId") in seen_ids
                or event.get("idempotencyKey") in seen_keys
                or _parse_rfc3339(event.get("occurredAt")) < previous_time
                or (
                    event.get("action") == "correct"
                    and event.get("details", {}).get("targetEventSha256")
                    not in {item["eventSha256"] for item in events[: len(seen_ids)]}
                )
            ):
                raise StudyOperationsError("study_operation_event_invalid", 409)
            challenge = challenges.get(event.get("challengeId"))
            self._verify_event_evidence(proposal_id, current, event, challenge)
            current = self._next_state(current, event)
            seen_ids.add(event["eventId"])
            seen_keys.add(event["idempotencyKey"])
            previous_time = _parse_rfc3339(event["occurredAt"])
        validate_operations_state(stored_state)
        if (
            current != stored_state
            or stored_state["permitId"] != permit_id
            or stored_state["permitSha256"] != permit["permitSha256"]
            or stored_state["releaseSha256"] != release["releaseSha256"]
            or stored_state["taskPlan"] != release["taskPlan"]
            or stored_state["eventCount"] != len(events)
        ):
            raise StudyOperationsError("study_operations_state_invalid", 409)
        return {
            "schema": "brainstem.study-operations-status/v1",
            "state": deepcopy(stored_state),
            "events": deepcopy(events),
        }

    def status(self, proposal_id, permit_id):
        return self.load_verified_status(proposal_id, permit_id)

    def _transition_details(self, action, details, state):
        details = _validate_details(action, details)
        if action == "correct":
            document = self.operations_dao.get_document(state["proposalId"])
            if details["targetEventSha256"] not in {
                item.get("eventSha256") for item in document["events"]
            }:
                raise StudyOperationsError("study_correction_target_invalid", 409)
        if action != "supersede":
            return details
        replacement_proposal = details["replacementProposalId"]
        if replacement_proposal == state["proposalId"]:
            raise StudyOperationsError("study_supersession_invalid", 409)
        replacement, next_release, _task_plan = self._permit(
            replacement_proposal, details["replacementPermitId"]
        )
        current_release = self.registry.release(
            state["offeringId"], state["releaseVersion"], state["releaseSha256"]
        )
        amendment = classify_amendment(current_release, next_release)
        return {
            "replacementProposalId": replacement_proposal,
            "replacementPermitId": replacement["permitId"],
            "replacementPermitSha256": replacement["permitSha256"],
            "replacementReleaseVersion": next_release["releaseVersion"],
            "replacementReleaseSha256": next_release["releaseSha256"],
            "amendment": amendment,
        }

    @staticmethod
    def _target(action, state):
        if action in SPECIAL_ACTIONS:
            if action in {"revoke", "supersede"} and state["disposition"] != "current":
                raise StudyOperationsError("study_operation_forbidden_state", 409)
            return state["lifecycleState"]
        if state["disposition"] != "current":
            raise StudyOperationsError("study_operation_forbidden_state", 409)
        try:
            return LIFECYCLE_ACTIONS[(state["lifecycleState"], action)]
        except KeyError as error:
            raise StudyOperationsError("study_operation_forbidden_state", 409) from error

    def _bundle(self, proposal_id, permit_id, action, idempotency_key, prior, details):
        if action not in ALL_ACTIONS:
            raise StudyOperationsError("study_operation_action_invalid")
        if (
            not isinstance(idempotency_key, str)
            or not IDEMPOTENCY_KEY.fullmatch(idempotency_key)
        ):
            raise StudyOperationsError("study_operation_idempotency_invalid")
        target = self._target(action, prior)
        resolved_details = self._transition_details(action, details, prior)
        value = {
            "schema": "brainstem.study-operation-bundle/v1",
            "proposalId": proposal_id,
            "permitId": permit_id,
            "permitSha256": prior["permitSha256"],
            "action": action,
            "idempotencyKey": idempotency_key,
            "priorStateSha256": prior["stateSha256"],
            "targetLifecycleState": target,
            "releaseSha256": prior["releaseSha256"],
            "taskPlanSha256": prior["taskPlan"]["sha256"],
            "details": resolved_details,
        }
        value["bundleSha256"] = content_sha256(value)
        return value

    def create_challenge(
        self,
        proposal_id,
        operator,
        origin,
        permit_id,
        action,
        expected_state_sha256,
        idempotency_key,
        details,
    ):
        proposal_id = normalize_proposal_id(proposal_id)
        operator = self._operator(operator)
        origin = self._origin(origin)
        if (
            not isinstance(expected_state_sha256, str)
            or not SHA256.fullmatch(expected_state_sha256)
        ):
            raise StudyOperationsError("study_operation_state_required")
        state, permit, _release, _task_plan = self._state(
            proposal_id, permit_id, persist=True
        )
        if (
            state["lifecycleState"] == "recruiting"
            and state["disposition"] == "current"
        ):
            verified = self.load_verified_status(proposal_id, permit_id)
            self._verified_recruitment_authority(verified)
            state = verified["state"]
        now = int(self.clock())
        if state["eventCount"] == 0 and _parse_rfc3339(permit["expiresAt"]) <= now:
            raise StudyOperationsError("study_permit_expired", 410)
        if state["stateSha256"] != expected_state_sha256:
            raise StudyOperationsError("study_operations_state_changed", 409)
        bundle = self._bundle(
            proposal_id, permit_id, action, idempotency_key, state, details
        )
        challenge_id = self.id_factory()
        nonce = self.nonce_factory()
        if (
            not isinstance(challenge_id, str)
            or not CHALLENGE_ID.fullmatch(challenge_id)
            or not isinstance(nonce, str)
            or not NONCE.fullmatch(nonce)
        ):
            raise RuntimeError("invalid generated study operation challenge")
        challenge = {
            "schema": "brainstem.study-operation-challenge/v1",
            "challenge_id": challenge_id,
            "proposal_id": proposal_id,
            "permit_id": permit_id,
            "operator_id": operator,
            "origin": origin,
            "chain_id": self.chain_id,
            "purpose": PURPOSE,
            "nonce": nonce,
            "issued_at": now,
            "expires_at": now + self.challenge_ttl,
            "bundle": bundle,
            "bundle_sha256": bundle["bundleSha256"],
            "idempotency_key": idempotency_key,
            "consumed_at": None,
        }
        challenge["message"] = _message(origin, operator, self.chain_id, challenge)
        try:
            self.operations_dao.create_challenge(
                proposal_id, state["stateSha256"], challenge, now
            )
        except StudyOperationsStateError as error:
            raise StudyOperationsError(str(error), 409) from error
        return {
            "challengeId": challenge_id,
            "message": challenge["message"],
            "expiresAt": rfc3339(challenge["expires_at"]),
            "chainId": self.chain_id,
            "method": "personal_sign",
            "bundle": deepcopy(bundle),
        }

    def _validate_challenge(self, challenge, proposal_id, operator, origin, challenge_id):
        if (
            not isinstance(challenge, dict)
            or challenge.get("schema") != "brainstem.study-operation-challenge/v1"
            or challenge.get("challenge_id") != challenge_id
            or challenge.get("proposal_id") != proposal_id
            or challenge.get("operator_id") != operator
            or challenge.get("origin") != origin
            or challenge.get("chain_id") != self.chain_id
            or challenge.get("purpose") != PURPOSE
            or not isinstance(challenge.get("nonce"), str)
            or not NONCE.fullmatch(challenge["nonce"])
            or type(challenge.get("issued_at")) is not int
            or type(challenge.get("expires_at")) is not int
            or not isinstance(challenge.get("bundle"), dict)
            or not isinstance(challenge.get("bundle_sha256"), str)
            or not SHA256.fullmatch(challenge["bundle_sha256"])
            or challenge["bundle"].get("bundleSha256")
            != challenge["bundle_sha256"]
            or challenge["bundle_sha256"]
            != content_sha256(
                {
                    key: item
                    for key, item in challenge["bundle"].items()
                    if key != "bundleSha256"
                }
            )
            or challenge.get("message")
            != _message(origin, operator, self.chain_id, challenge)
        ):
            raise StudyOperationsError("study_operation_challenge_unavailable", 401)

    @staticmethod
    def _next_state(state, event):
        result = deepcopy(state)
        result["lifecycleState"] = event["targetLifecycleState"]
        if event["action"] == "revoke":
            result["disposition"] = "revoked"
        elif event["action"] == "supersede":
            result["disposition"] = "superseded"
            result["supersededBy"] = deepcopy(event["details"])
        result["eventCount"] += 1
        result["lastEventSha256"] = event["eventSha256"]
        result["updatedAt"] = event["occurredAt"]
        result["stateSha256"] = state_sha256(result)
        return result

    def _begin_recruitment_authority(
        self, state, permit_id, claim_id, now, lease_expires_at
    ):
        offering_id = state["offeringId"]
        release_sha256 = state["releaseSha256"]
        try:
            authority = self.operations_dao.get_recruitment_authority(
                offering_id, release_sha256
            )
            replace_claim_id = None
            if (
                isinstance(authority, dict)
                and authority.get("state") == "pending"
                and authority.get("claim_id") != claim_id
            ):
                if authority.get("lease_expires_at", now + 1) > now:
                    raise StudyOperationsStateError(
                        "Study recruitment authority already claimed"
                    )
                owner = self.load_verified_status(
                    authority["proposal_id"], authority["permit_id"]
                )
                owner_state = owner["state"]
                if (
                    owner_state["offeringId"] != offering_id
                    or owner_state["releaseSha256"] != release_sha256
                ):
                    raise StudyOperationsStateError(
                        "Study recruitment authority unavailable"
                    )
                if (
                    owner_state["lifecycleState"] == "recruiting"
                    and owner_state["disposition"] == "current"
                ):
                    self.operations_dao.finalize_recruitment_authority(
                        offering_id,
                        release_sha256,
                        authority["proposal_id"],
                        authority["claim_id"],
                    )
                    raise StudyOperationsStateError(
                        "Study recruitment authority already active"
                    )
                replace_claim_id = authority["claim_id"]
            return self.operations_dao.claim_recruitment_authority(
                offering_id,
                release_sha256,
                state["proposalId"],
                permit_id,
                claim_id,
                now,
                lease_expires_at,
                replace_claim_id,
            )
        except (StudyOperationsError, StudyOperationsStateError) as error:
            raise StudyOperationsError(
                "study_recruitment_authority_conflict", 409
            ) from error

    def _finalize_recruitment_authority(self, state, claim_id):
        try:
            return self.operations_dao.finalize_recruitment_authority(
                state["offeringId"],
                state["releaseSha256"],
                state["proposalId"],
                claim_id,
            )
        except StudyOperationsStateError as error:
            raise StudyOperationsError(
                "study_recruitment_authority_pending", 503
            ) from error

    def _reconcile_recruitment_transition(
        self,
        state,
        challenge_id,
        bundle_sha256,
        event,
        consume_error,
    ):
        try:
            challenge = self.operations_dao.get_challenge(
                state["proposalId"], challenge_id
            )
        except Exception:
            raise StudyOperationsError(
                "study_recruitment_transition_pending", 503
            ) from consume_error
        if (
            not isinstance(challenge, dict)
            or challenge.get("challenge_id") != challenge_id
            or challenge.get("bundle_sha256") != bundle_sha256
        ):
            raise StudyOperationsError(
                "study_recruitment_transition_pending", 503
            ) from consume_error
        if challenge.get("consumed_at") is None:
            raise StudyOperationsError(
                "study_recruitment_transition_pending", 503
            ) from consume_error
        try:
            stored = self.operations_dao.idempotent_result(
                state["proposalId"], challenge_id, bundle_sha256
            )
            verified = self.load_verified_status(
                state["proposalId"], challenge["permit_id"]
            )
        except Exception:
            raise StudyOperationsError(
                "study_recruitment_transition_pending", 503
            ) from consume_error
        if (
            not isinstance(stored, dict)
            or not isinstance(verified, dict)
            or not isinstance(verified.get("events"), list)
            or not isinstance(verified.get("state"), dict)
            or stored.get("event") != event
            or event not in verified["events"]
            or verified["state"].get("lifecycleState") != "recruiting"
            or verified["state"].get("disposition") != "current"
        ):
            raise StudyOperationsError(
                "study_recruitment_transition_pending", 503
            ) from consume_error
        self._finalize_recruitment_authority(
            verified["state"], challenge_id
        )
        return {
            "event": deepcopy(stored["event"]),
            "state": deepcopy(verified["state"]),
        }

    def _verified_recruitment_authority(self, verified):
        state = verified["state"]
        try:
            authority = self.operations_dao.get_recruitment_authority(
                state["offeringId"], state["releaseSha256"]
            )
            if (
                isinstance(authority, dict)
                and authority.get("state") == "pending"
                and authority.get("proposal_id") == state["proposalId"]
                and authority.get("permit_id") == state["permitId"]
                and any(
                    event.get("action") == "recruit"
                    and event.get("challengeId") == authority.get("claim_id")
                    for event in verified["events"]
                )
            ):
                authority = self.operations_dao.finalize_recruitment_authority(
                    state["offeringId"],
                    state["releaseSha256"],
                    state["proposalId"],
                    authority["claim_id"],
                )
            if (
                not isinstance(authority, dict)
                or authority.get("state") != "finalized"
                or authority.get("proposal_id") != state["proposalId"]
                or authority.get("permit_id") != state["permitId"]
            ):
                raise StudyOperationsStateError(
                    "Study recruitment authority changed"
                )
            return authority
        except StudyOperationsStateError as error:
            raise StudyOperationsError(
                "study_recruitment_authority_changed", 409
            ) from error

    def apply(self, proposal_id, operator, origin, challenge_id, signature):
        proposal_id = normalize_proposal_id(proposal_id)
        operator = self._operator(operator)
        origin = self._origin(origin)
        if not isinstance(challenge_id, str) or not CHALLENGE_ID.fullmatch(challenge_id):
            raise StudyOperationsError("study_operation_challenge_invalid")
        try:
            challenge = self.operations_dao.get_challenge(proposal_id, challenge_id)
        except StudyOperationsStateError as error:
            raise StudyOperationsError("study_operation_challenge_unavailable", 401) from error
        self._validate_challenge(challenge, proposal_id, operator, origin, challenge_id)
        try:
            verify_wallet_signature(challenge["message"], signature, operator)
        except ParticipantAuthError as error:
            raise StudyOperationsError("study_operator_signature_invalid", 401) from error
        if challenge.get("consumed_at") is not None:
            try:
                stored = self.operations_dao.idempotent_result(
                    proposal_id, challenge_id, challenge["bundle_sha256"]
                )
            except StudyOperationsStateError as error:
                raise StudyOperationsError(str(error), 409) from error
            verified = self.load_verified_status(
                proposal_id, challenge["permit_id"]
            )
            if stored["event"] not in verified["events"]:
                raise StudyOperationsError("study_operation_evidence_invalid", 409)
            if stored["event"].get("action") == "recruit":
                self._verified_recruitment_authority(verified)
            return {
                "schema": "brainstem.study-operation-result/v1",
                "event": deepcopy(stored["event"]),
                "state": deepcopy(verified["state"]),
            }
        now = int(self.clock())
        if challenge["expires_at"] <= now:
            raise StudyOperationsError("study_operation_challenge_expired", 410)
        permit_id = challenge.get("permit_id")
        state, permit, _release, _task_plan = self._state(proposal_id, permit_id)
        stored_bundle = challenge["bundle"]
        current_bundle = self._bundle(
            proposal_id,
            permit_id,
            stored_bundle.get("action"),
            stored_bundle.get("idempotencyKey"),
            state,
            {
                key: value
                for key, value in stored_bundle.get("details", {}).items()
                if key
                in {
                    "reasonCode",
                    "evidenceSha256",
                    "targetEventSha256",
                    "replacementProposalId",
                    "replacementPermitId",
                }
            },
        )
        if current_bundle != stored_bundle:
            raise StudyOperationsError("study_operations_state_changed", 409)
        if (
            state["eventCount"] == 0
            and _parse_rfc3339(permit["expiresAt"]) <= now
        ):
            raise StudyOperationsError("study_permit_expired", 410)
        authority_claimed = False
        if current_bundle["action"] == "recruit":
            claim_time = int(self.clock())
            if challenge["expires_at"] <= claim_time:
                raise StudyOperationsError(
                    "study_operation_challenge_expired", 410
                )
            self._begin_recruitment_authority(
                state,
                permit_id,
                challenge_id,
                claim_time,
                challenge["expires_at"],
            )
            authority_claimed = True
        consumed_at = int(self.clock())
        if challenge["expires_at"] <= consumed_at:
            raise StudyOperationsError(
                "study_operation_challenge_expired", 410
            )
        if (
            state["eventCount"] == 0
            and _parse_rfc3339(permit["expiresAt"]) <= consumed_at
        ):
            raise StudyOperationsError("study_permit_expired", 410)
        event_id = "operation_{}".format(challenge_id)
        event = {
            "schema": "brainstem.study-operation-event/v1",
            "eventId": event_id,
            "challengeId": challenge_id,
            "proposalId": proposal_id,
            "permitId": permit_id,
            "action": current_bundle["action"],
            "idempotencyKey": current_bundle["idempotencyKey"],
            "operatorId": operator,
            "priorStateSha256": state["stateSha256"],
            "targetLifecycleState": current_bundle["targetLifecycleState"],
            "bundleSha256": current_bundle["bundleSha256"],
            "details": deepcopy(current_bundle["details"]),
            "occurredAt": rfc3339(consumed_at),
            "signedMessageSha256": _text_sha256(challenge["message"]),
            "operatorSignatureSha256": _text_sha256(signature),
        }
        event["eventSha256"] = _event_sha256(event)
        next_state = self._next_state(state, event)
        try:
            stored = self.operations_dao.consume_transition(
                proposal_id,
                challenge_id,
                state["stateSha256"],
                current_bundle["bundleSha256"],
                event,
                next_state,
                signature,
                consumed_at,
            )
        except Exception as error:
            if authority_claimed:
                stored = self._reconcile_recruitment_transition(
                    state,
                    challenge_id,
                    current_bundle["bundleSha256"],
                    event,
                    error,
                )
                authority_claimed = False
            elif isinstance(error, StudyOperationsStateError):
                status = 410 if "expired" in str(error).lower() else 409
                raise StudyOperationsError(str(error), status) from error
            else:
                raise
        if authority_claimed:
            self._finalize_recruitment_authority(
                stored["state"], challenge_id
            )
        return {
            "schema": "brainstem.study-operation-result/v1",
            "event": deepcopy(stored["event"]),
            "state": deepcopy(stored["state"]),
        }

    def recruitment_contract(
        self,
        offering_id,
        release_sha256,
        now,
        participant_binding_key_id,
        participant_binding_key_commitment_sha256,
    ):
        try:
            authority = self.operations_dao.get_recruitment_authority(
                offering_id, release_sha256
            )
            if (
                not isinstance(authority, dict)
                or authority.get("state") != "finalized"
            ):
                raise StudyOperationsStateError(
                    "Study recruitment authority unavailable"
                )
            document = self.operations_dao.get_document(
                authority["proposal_id"]
            )
            verified = self.load_verified_status(
                authority["proposal_id"], authority["permit_id"]
            )
            state = verified["state"]
        except (
            KeyError,
            StudyOperationsError,
            StudyOperationsStateError,
        ) as error:
            raise StudyOperationsError("study_not_recruiting", 409) from error
        if (
            state["proposalId"] != authority["proposal_id"]
            or state["permitId"] != authority["permit_id"]
            or state["offeringId"] != offering_id
            or state["releaseSha256"] != release_sha256
            or (
                document.get("participant_binding_key_id") is not None
                and document.get("participant_binding_key_id")
                != participant_binding_key_id
            )
            or (
                document.get("participant_binding_key_commitment_sha256")
                is not None
                and document.get("participant_binding_key_commitment_sha256")
                != participant_binding_key_commitment_sha256
            )
        ):
            raise StudyOperationsError("study_recruitment_authority_changed", 409)
        if (
            state["lifecycleState"] != "recruiting"
            or state["disposition"] != "current"
        ):
            raise StudyOperationsError("study_not_recruiting", 409)
        self._verified_recruitment_authority(verified)
        _current, _permit, release, task_plan = self._state(
            state["proposalId"], state["permitId"]
        )
        starts_at, ends_at = task_window(task_plan, now)
        return {
            "proposalId": state["proposalId"],
            "permitId": state["permitId"],
            "operationStateSha256": state["stateSha256"],
            "taskPlan": deepcopy(release["taskPlan"]),
            "startsAt": starts_at,
            "endsAt": ends_at,
            "participantBindingKeyId": participant_binding_key_id,
            "participantBindingKeyCommitmentSha256": (
                participant_binding_key_commitment_sha256
            ),
            "recruitmentTicketTtlSeconds": self.challenge_ttl,
        }

    def reserve_recruitment(
        self,
        offering_id,
        release_sha256,
        participant_binding_sha256,
        participant_binding_key_id,
        participant_binding_key_commitment_sha256,
        reservation_key_sha256,
        consumed_at,
    ):
        if (
            not isinstance(participant_binding_sha256, str)
            or not SHA256.fullmatch(participant_binding_sha256)
            or not isinstance(participant_binding_key_id, str)
            or not 1 <= len(participant_binding_key_id) <= 64
            or not participant_binding_key_id.isascii()
            or not all(
                character.isalnum() or character in "._-"
                for character in participant_binding_key_id
            )
            or not isinstance(participant_binding_key_commitment_sha256, str)
            or not SHA256.fullmatch(
                participant_binding_key_commitment_sha256
            )
            or not isinstance(reservation_key_sha256, str)
            or not SHA256.fullmatch(reservation_key_sha256)
            or type(consumed_at) is not int
        ):
            raise StudyOperationsError("study_participant_binding_invalid")
        contract = self.recruitment_contract(
            offering_id,
            release_sha256,
            consumed_at,
            participant_binding_key_id,
            participant_binding_key_commitment_sha256,
        )
        status = self.load_verified_status(
            contract["proposalId"], contract["permitId"]
        )
        state = status["state"]
        try:
            activation_profile = self.registry.activation_profile(
                state["offeringId"],
                state["releaseVersion"],
                state["releaseSha256"],
            )
            maximum_participants = activation_profile["content"]["limits"][
                "maximumParticipants"
            ]
        except (KeyError, StudyRegistryError) as error:
            raise StudyOperationsError(
                "study_recruitment_profile_invalid", 409
            ) from error
        if (
            state["stateSha256"] != contract["operationStateSha256"]
            or state["lifecycleState"] != "recruiting"
            or state["disposition"] != "current"
        ):
            raise StudyOperationsError("study_not_recruiting", 409)
        ticket_id = self.id_factory()
        if (
            not isinstance(ticket_id, str)
            or not RECRUITMENT_TICKET_ID.fullmatch(ticket_id)
        ):
            raise RuntimeError("invalid generated study recruitment ticket")
        ticket = {
            "schema": "brainstem.study-recruitment-ticket/v3",
            "ticket_id": ticket_id,
            "proposal_id": state["proposalId"],
            "permit_id": state["permitId"],
            "participant_binding_key_id": participant_binding_key_id,
            "participant_binding_key_commitment_sha256": (
                participant_binding_key_commitment_sha256
            ),
            "participant_binding_sha256": participant_binding_sha256,
            "reservation_key_sha256": reservation_key_sha256,
            "operation_state_sha256": state["stateSha256"],
            "release_sha256": state["releaseSha256"],
            "task_plan_sha256": state["taskPlan"]["sha256"],
            "issued_at": consumed_at,
            "expires_at": consumed_at + self.challenge_ttl,
            "ticket_sha256": None,
            "finalized_at": None,
            "enrollment_sha256": None,
            "cancelled_at": None,
        }
        ticket["ticket_sha256"] = _ticket_sha256(ticket)
        try:
            ticket = self.operations_dao.reserve_recruitment(
                state["proposalId"],
                state["stateSha256"],
                ticket,
                consumed_at,
                maximum_participants,
            )
        except StudyOperationsStateError as error:
            raise StudyOperationsError(str(error), 409) from error
        return {
            **contract,
            "participantBindingSha256": participant_binding_sha256,
            "recruitmentReservationKeySha256": ticket[
                "reservation_key_sha256"
            ],
            "recruitmentTicketId": ticket["ticket_id"],
            "recruitmentTicketSha256": ticket["ticket_sha256"],
            "recruitmentTicketIssuedAt": ticket["issued_at"],
            "recruitmentTicketExpiresAt": ticket["expires_at"],
        }

    def _live_recruitment_ticket(
        self,
        proposal_id,
        ticket_id,
        ticket_sha256,
        participant_binding_sha256,
        participant_binding_key_id,
        participant_binding_key_commitment_sha256,
        at_time=None,
    ):
        try:
            ticket = self.operations_dao.get_recruitment_ticket(
                proposal_id, ticket_id
            )
        except StudyOperationsStateError as error:
            raise StudyOperationsError(
                "study_recruitment_ticket_unavailable", 409
            ) from error
        _validate_recruitment_ticket(ticket)
        now = int(self.clock()) if at_time is None else at_time
        if (
            ticket["ticket_sha256"] != ticket_sha256
            or ticket["participant_binding_key_id"]
            != participant_binding_key_id
            or ticket["participant_binding_key_commitment_sha256"]
            != participant_binding_key_commitment_sha256
            or ticket["participant_binding_sha256"]
            != participant_binding_sha256
        ):
            raise StudyOperationsError(
                "study_recruitment_ticket_invalid", 409
            )
        if ticket["finalized_at"] is not None:
            raise StudyOperationsError("study_recruitment_ticket_finalized", 409)
        if ticket["cancelled_at"] is not None:
            raise StudyOperationsError("study_recruitment_ticket_cancelled", 409)
        if ticket["expires_at"] <= now:
            raise StudyOperationsError("study_recruitment_ticket_expired", 410)
        current = self.load_verified_status(
            ticket["proposal_id"], ticket["permit_id"]
        )["state"]
        if (
            current["stateSha256"] != ticket["operation_state_sha256"]
            or current["lifecycleState"] != "recruiting"
            or current["disposition"] != "current"
            or current["releaseSha256"] != ticket["release_sha256"]
            or current["taskPlan"]["sha256"] != ticket["task_plan_sha256"]
        ):
            raise StudyOperationsError("study_recruitment_state_changed", 409)
        return deepcopy(ticket)

    def assert_recruitment_ticket(
        self,
        proposal_id,
        ticket_id,
        ticket_sha256,
        participant_binding_sha256,
        participant_binding_key_id,
        participant_binding_key_commitment_sha256,
    ):
        return self._live_recruitment_ticket(
            proposal_id,
            ticket_id,
            ticket_sha256,
            participant_binding_sha256,
            participant_binding_key_id,
            participant_binding_key_commitment_sha256,
        )

    def finalize_recruitment(
        self,
        proposal_id,
        ticket_id,
        ticket_sha256,
        participant_binding_sha256,
        participant_binding_key_id,
        participant_binding_key_commitment_sha256,
        enrollment_sha256,
        consumed_at,
    ):
        try:
            existing = self.operations_dao.get_recruitment_ticket(
                normalize_proposal_id(proposal_id), ticket_id
            )
        except (StudyOperationsStateError, StudyProposalError) as error:
            raise StudyOperationsError(
                "study_recruitment_finalization_failed", 409
            ) from error
        _validate_recruitment_ticket(existing)
        if (
            type(consumed_at) is not int
            or existing["issued_at"] != consumed_at
        ):
            raise StudyOperationsError(
                "study_recruitment_finalization_failed", 409
            )
        if existing["finalized_at"] is not None:
            if (
                existing["ticket_sha256"] != ticket_sha256
                or existing["participant_binding_key_id"]
                != participant_binding_key_id
                or existing["participant_binding_key_commitment_sha256"]
                != participant_binding_key_commitment_sha256
                or existing["participant_binding_sha256"]
                != participant_binding_sha256
                or existing["enrollment_sha256"] != enrollment_sha256
                or existing["finalized_at"] != consumed_at
                or existing["cancelled_at"] is not None
            ):
                raise StudyOperationsError(
                    "study_recruitment_finalization_failed", 409
                )
            return self.load_verified_recruitment_ticket(
                proposal_id,
                existing["permit_id"],
                ticket_id,
                ticket_sha256,
                participant_binding_sha256,
                participant_binding_key_id,
                participant_binding_key_commitment_sha256,
                enrollment_sha256,
                consumed_at,
            )
        self._live_recruitment_ticket(
            proposal_id,
            ticket_id,
            ticket_sha256,
            participant_binding_sha256,
            participant_binding_key_id,
            participant_binding_key_commitment_sha256,
            at_time=consumed_at,
        )
        try:
            return self.operations_dao.finalize_recruitment(
                proposal_id,
                ticket_id,
                ticket_sha256,
                enrollment_sha256,
                consumed_at,
            )
        except StudyOperationsStateError as error:
            raise StudyOperationsError(
                "study_recruitment_finalization_failed", 409
            ) from error

    def cancel_recruitment(self, proposal_id, ticket_id):
        if not isinstance(ticket_id, str) or not RECRUITMENT_TICKET_ID.fullmatch(
            ticket_id
        ):
            return
        try:
            self.operations_dao.cancel_recruitment(
                normalize_proposal_id(proposal_id), ticket_id, int(self.clock())
            )
        except StudyOperationsStateError:
            return

    def cancel_recruitment_reservation(
        self, proposal_id, reservation_key_sha256
    ):
        if (
            not isinstance(reservation_key_sha256, str)
            or not SHA256.fullmatch(reservation_key_sha256)
        ):
            return False
        try:
            self.operations_dao.cancel_recruitment_reservation(
                normalize_proposal_id(proposal_id),
                reservation_key_sha256,
                int(self.clock()),
            )
            return True
        except (StudyOperationsStateError, StudyProposalError):
            return False

    def load_verified_recruitment_ticket(
        self,
        proposal_id,
        permit_id,
        ticket_id,
        ticket_sha256,
        participant_binding_sha256,
        participant_binding_key_id,
        participant_binding_key_commitment_sha256,
        enrollment_sha256,
        consumed_at,
    ):
        proposal_id = normalize_proposal_id(proposal_id)
        try:
            ticket = self.operations_dao.get_recruitment_ticket(
                proposal_id, ticket_id
            )
        except StudyOperationsStateError as error:
            raise StudyOperationsError(
                "study_recruitment_evidence_unavailable", 409
            ) from error
        _validate_recruitment_ticket(ticket)
        authority = self.operations_dao.get_document(proposal_id)
        if (
            ticket["proposal_id"] != proposal_id
            or ticket["permit_id"] != permit_id
            or ticket["ticket_sha256"] != ticket_sha256
            or ticket["participant_binding_key_id"]
            != participant_binding_key_id
            or ticket["participant_binding_key_commitment_sha256"]
            != participant_binding_key_commitment_sha256
            or ticket["participant_binding_sha256"]
            != participant_binding_sha256
            or ticket["enrollment_sha256"] != enrollment_sha256
            or ticket["issued_at"] != consumed_at
            or ticket["finalized_at"] != consumed_at
            or ticket["finalized_at"] is None
            or ticket["cancelled_at"] is not None
            or authority.get("participant_binding_key_id")
            != participant_binding_key_id
            or authority.get(
                "participant_binding_key_commitment_sha256"
            )
            != participant_binding_key_commitment_sha256
        ):
            raise StudyOperationsError("study_recruitment_evidence_invalid", 409)
        status = self.load_verified_status(proposal_id, permit_id)
        try:
            self._verified_recruitment_authority(status)
        except (StudyOperationsError, StudyOperationsStateError) as error:
            raise StudyOperationsError(
                "study_recruitment_evidence_invalid", 409
            ) from error
        permit, _release, _task_plan = self._permit(proposal_id, permit_id)
        replay = _initial_state(permit)
        recruiting_state = None
        if replay["stateSha256"] == ticket["operation_state_sha256"]:
            recruiting_state = replay
        for event in status["events"]:
            replay = self._next_state(replay, event)
            if replay["stateSha256"] == ticket["operation_state_sha256"]:
                recruiting_state = replay
        if (
            recruiting_state is None
            or recruiting_state["lifecycleState"] != "recruiting"
            or recruiting_state["disposition"] != "current"
            or recruiting_state["releaseSha256"] != ticket["release_sha256"]
            or recruiting_state["taskPlan"]["sha256"]
            != ticket["task_plan_sha256"]
        ):
            raise StudyOperationsError("study_recruitment_evidence_invalid", 409)
        return deepcopy(ticket)

    def enrollment_requires_renewal(self, enrollment):
        if not isinstance(enrollment, dict):
            return False
        try:
            verified = self.load_verified_status(
                enrollment["proposalId"], enrollment["permitId"]
            )
            state = verified["state"]
            self._verified_recruitment_authority(verified)
        except (KeyError, StudyOperationsStateError, StudyOperationsError):
            return True
        if (
            state["permitId"] != enrollment.get("permitId")
            or state["releaseSha256"] != enrollment.get("releaseSha256")
            or state["taskPlan"] != enrollment.get("taskPlan")
        ):
            return True
        return state["disposition"] in {"revoked", "superseded"}

    def load_verified_operation(self, proposal_id, permit_id, capability):
        """Return the one verified snapshot that authorizes a fixed capability."""
        allowed = {
            "recruitment": {"recruiting"},
            "collection": {"active"},
            "materialization": {"active"},
            "lease": {"active"},
            "reminder": {"active"},
        }
        if capability not in allowed:
            raise StudyOperationsError("study_operation_capability_invalid")
        verified = self.load_verified_status(proposal_id, permit_id)
        self._verified_recruitment_authority(verified)
        state = verified["state"]
        if (
            state["disposition"] != "current"
            or state["lifecycleState"] not in allowed[capability]
        ):
            raise StudyOperationsError("study_operation_not_allowed", 409)
        return verified

    def operation_allowed(self, proposal_id, permit_id, capability):
        """Fail closed unless the verified lifecycle permits a fixed capability."""
        try:
            self.load_verified_operation(proposal_id, permit_id, capability)
        except (KeyError, StudyOperationsError, StudyOperationsStateError):
            return False
        return True

    def participant_tasks(
        self,
        enrollment,
        participant_id,
        completion_source=None,
    ):
        if (
            not isinstance(enrollment, dict)
            or not isinstance(participant_id, str)
            or not participant_id
            or type(enrollment.get("startsAt")) is not int
            or type(enrollment.get("endsAt")) is not int
        ):
            raise StudyOperationsError("study_enrollment_invalid", 409)
        try:
            status = self.load_verified_status(
                enrollment["proposalId"], enrollment["permitId"]
            )
            self._verified_recruitment_authority(status)
            state = status["state"]
            task_plan = self.registry.task_plan(
                state["offeringId"],
                state["releaseVersion"],
                state["releaseSha256"],
            )
        except (KeyError, StudyRegistryError) as error:
            raise StudyOperationsError("study_enrollment_invalid", 409) from error
        if (
            enrollment.get("offeringId") != state["offeringId"]
            or enrollment.get("releaseVersion") != state["releaseVersion"]
            or enrollment.get("releaseSha256") != state["releaseSha256"]
            or enrollment.get("taskPlan") != state["taskPlan"]
            or task_plan.get("sha256") != state["taskPlan"].get("sha256")
            or enrollment["endsAt"] <= enrollment["startsAt"]
            or enrollment["startsAt"] % 86400 != 0
            or enrollment["endsAt"]
            != enrollment["startsAt"]
            + max(
                task["windowEndDay"]
                for task in task_plan["content"]["tasks"]
            )
            * 86400
        ):
            raise StudyOperationsError("study_enrollment_invalid", 409)
        now = int(self.clock())
        source = completion_source or EmptyTaskCompletionSource()
        try:
            completions = source.completions(participant_id, deepcopy(enrollment))
        except Exception as error:
            raise StudyOperationsError(
                "study_task_completion_source_unavailable", 503
            ) from error
        if not isinstance(completions, list):
            raise StudyOperationsError("study_task_completion_evidence_invalid", 503)

        occurrences = []
        expected = {}
        for task in task_plan["content"]["tasks"]:
            for index in range(task["maximumOccurrences"]):
                opens_at = enrollment["startsAt"] + (
                    task["windowStartDay"] + index * task["cadenceDays"]
                ) * 86400
                closes_at = min(
                    enrollment["startsAt"] + task["windowEndDay"] * 86400,
                    opens_at + task["cadenceDays"] * 86400,
                )
                if opens_at >= closes_at:
                    break
                key = (task["taskId"], index + 1)
                expected[key] = (task, opens_at, closes_at)
                occurrences.append((key, task, opens_at, closes_at))
        if len(completions) > len(occurrences):
            raise StudyOperationsError("study_task_completion_evidence_invalid", 503)
        completed = {}
        for item in completions:
            key = (
                item.get("taskId") if isinstance(item, dict) else None,
                item.get("occurrence") if isinstance(item, dict) else None,
            )
            fields = {
                "taskId",
                "occurrence",
                "capability",
                "completedAt",
                "evidenceSha256",
            }
            task, opens_at, closes_at = expected.get(key, (None, None, None))
            if (
                not isinstance(item, dict)
                or set(item) != fields
                or key in completed
                or task is None
                or item.get("capability") != task["capability"]
                or type(item.get("completedAt")) is not int
                or not opens_at <= item["completedAt"] < closes_at
                or item["completedAt"] > now
                or not isinstance(item.get("evidenceSha256"), str)
                or not SHA256.fullmatch(item["evidenceSha256"])
            ):
                raise StudyOperationsError(
                    "study_task_completion_evidence_invalid", 503
                )
            completed[key] = item["completedAt"]

        is_open = (
            enrollment.get("state") == "active"
            and state["disposition"] == "current"
            and state["lifecycleState"] == "active"
        )
        tasks = []
        for key, task, opens_at, closes_at in occurrences:
            completed_at = completed.get(key)
            if completed_at is not None:
                task_state = "completed"
            elif not is_open:
                task_state = "closed"
            elif now >= closes_at:
                task_state = "missed"
            elif now < opens_at:
                task_state = "upcoming"
            else:
                task_state = "due"
            tasks.append(
                {
                    "taskId": task["taskId"],
                    "kind": task["kind"],
                    "capability": task["capability"],
                    "occurrence": key[1],
                    "opensAt": opens_at,
                    "closesAt": closes_at,
                    "status": task_state,
                    "completedAt": completed_at,
                }
            )
        return {
            "schema": "brainstem.participant-study-tasks/v1",
            "offeringId": state["offeringId"],
            "releaseVersion": state["releaseVersion"],
            "releaseSha256": state["releaseSha256"],
            "lifecycleState": state["lifecycleState"],
            "disposition": state["disposition"],
            "taskPlan": deepcopy(state["taskPlan"]),
            "tasks": tasks,
        }

    def researcher_projection(self, proposal_id, permit_id, metrics_source):
        proposal_id = normalize_proposal_id(proposal_id)
        state, _permit, _release, _task_plan = self._state(
            proposal_id, permit_id, persist=True
        )
        published_on = datetime.fromtimestamp(
            int(self.clock()), timezone.utc
        ).strftime("%Y-%m-%d")
        try:
            snapshot = self.operations_dao.privacy_snapshot(
                proposal_id, published_on
            )
        except StudyOperationsStateError as error:
            raise StudyOperationsError(
                "study_privacy_snapshot_unavailable", 503
            ) from error
        if snapshot is None:
            try:
                counts = metrics_source.counts(deepcopy(state))
            except StudyOperationsError:
                raise
            except Exception as error:
                raise StudyOperationsError(
                    "study_privacy_metrics_unavailable", 503
                ) from error
            if (
                not isinstance(counts, dict)
                or set(counts) != set(PRIVACY_METRICS)
            ):
                raise StudyOperationsError("study_privacy_metrics_invalid", 503)
            snapshot = {
                "schema": "brainstem.study-privacy-snapshot/v1",
                "publishedOn": published_on,
                "stateSha256": state["stateSha256"],
                "bands": {
                    key: privacy_band(counts[key]) for key in PRIVACY_METRICS
                },
            }
            try:
                snapshot = self.operations_dao.publish_privacy_snapshot(
                    proposal_id, state["stateSha256"], snapshot
                )
            except StudyOperationsStateError as error:
                raise StudyOperationsError(
                    "study_privacy_snapshot_unavailable", 503
                ) from error
        _validate_privacy_snapshot(snapshot, published_on)
        current = self.load_verified_status(proposal_id, permit_id)
        state = current["state"]
        timeline_state_sha256s = {
            state["stateSha256"],
            *(event["priorStateSha256"] for event in current["events"]),
        }
        if snapshot["stateSha256"] not in timeline_state_sha256s:
            raise StudyOperationsError("study_privacy_snapshot_invalid", 503)
        return {
            "schema": "brainstem.researcher-study-operations/v1",
            "proposalId": proposal_id,
            "permitId": permit_id,
            "offeringId": state["offeringId"],
            "releaseVersion": state["releaseVersion"],
            "releaseSha256": state["releaseSha256"],
            "lifecycleState": state["lifecycleState"],
            "disposition": state["disposition"],
            "supersededBy": deepcopy(state["supersededBy"]),
            "hasCorrections": any(
                event["action"] == "correct" for event in current["events"]
            ),
            "stateSha256": state["stateSha256"],
            "publishedOn": snapshot["publishedOn"],
            "snapshotStateSha256": snapshot["stateSha256"],
            "snapshotCurrent": snapshot["stateSha256"] == state["stateSha256"],
            "bands": deepcopy(snapshot["bands"]),
        }
