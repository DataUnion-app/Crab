from copy import deepcopy
import hashlib
import threading

from eth_account.messages import encode_defunct
from eth_account import Account
import pytest

from commands.dataunions.brainstem.study_activation import StudyActivationService
from commands.dataunions.brainstem.study_operations import (
    ALL_ACTIONS,
    LIFECYCLE_ACTIONS,
    StudyOperationsError,
    StudyOperationsMetricsSource,
    StudyOperationsService,
    classify_amendment,
    privacy_band,
    state_sha256,
    task_window,
)
from commands.dataunions.brainstem.study_proposals import StudyProposalWorkflow
from commands.dataunions.brainstem.study_registry import (
    COMMUNITY_QUESTIONNAIRE_ID,
    DEFAULT_STUDY_REGISTRY,
    RECORDING_FEASIBILITY_ID,
)
from commands.dataunions.studies.registry import StudyRegistryError, content_sha256
from commands.users.participant_auth import rfc3339
from dao.study_operations_dao import (
    MAX_ACTIVE_CHALLENGES,
    MAX_CHALLENGE_HISTORY,
    StudyOperationsStateError,
)
from tests.commands.metadata.test_brainstem_study_activation import (
    AUTHOR,
    DOMAINS,
    OPERATOR,
    ORIGIN,
    REVIEWERS,
    ActivationDao,
    Clock,
    ProposalDao,
    payload,
)
from tests.commands.metadata.test_brainstem_study_registry import amended_registry


NOW = 1785595200
METRIC_KEYS = ("recruitment", "adherence", "dataQuality", "resultAvailability")
BINDING_KEY_ID = "binding-v1"
BINDING_COMMITMENT = "a" * 64
RESERVATION_KEY = "b" * 64


class Ids:
    def __init__(self, start=0):
        self.value = start

    def __call__(self, prefix=None):
        self.value += 1
        if prefix is None:
            return format(self.value, "032x")
        return "{}_{}".format(prefix, format(self.value, "x"))


class OperationsDao:
    def __init__(self):
        self.docs = {}
        self.authorities = {}
        self.lock = threading.Lock()
        self.fail_consume_once = False
        self.fail_finalize_authority_once = False

    def ensure_state(self, proposal_id, initial):
        with self.lock:
            document = self.docs.setdefault(
                proposal_id,
                {
                    "document_type": "brainstem_study_operations",
                    "proposal_id": proposal_id,
                    "state": deepcopy(initial),
                    "events": [],
                    "challenges": {},
                    "privacy_snapshots": [],
                    "recruitment_tickets": {},
                    "participant_binding_key_id": None,
                    "participant_binding_key_commitment_sha256": None,
                },
            )
            return deepcopy(document["state"])

    def get_document(self, proposal_id):
        with self.lock:
            if proposal_id not in self.docs:
                raise StudyOperationsStateError("Study operations unavailable")
            return deepcopy(self.docs[proposal_id])

    def get_state(self, proposal_id):
        return self.get_document(proposal_id)["state"]

    def get_recruitment_authority(self, offering_id, release_sha256):
        with self.lock:
            key = (offering_id, release_sha256)
            return deepcopy(self.authorities.get(key))

    def claim_recruitment_authority(
        self,
        offering_id,
        release_sha256,
        proposal_id,
        permit_id,
        claim_id,
        now,
        lease_expires_at,
        replace_claim_id=None,
    ):
        with self.lock:
            key = (offering_id, release_sha256)
            existing = self.authorities.get(key)
            if (
                existing is not None
                and existing["state"] in {"pending", "finalized"}
                and existing["proposal_id"] == proposal_id
                and existing["permit_id"] == permit_id
                and existing["claim_id"] == claim_id
            ):
                return deepcopy(existing)
            replace_stale = (
                existing is not None
                and existing["state"] == "pending"
                and existing["claim_id"] == replace_claim_id
                and existing["lease_expires_at"] <= now
            )
            if (
                existing is not None
                and existing["state"] != "released"
                and not replace_stale
            ):
                raise StudyOperationsStateError(
                    "Study recruitment authority already claimed"
                )
            authority = {
                "document_type": "brainstem_study_recruitment_authority",
                "offering_id": offering_id,
                "release_sha256": release_sha256,
                "proposal_id": proposal_id,
                "permit_id": permit_id,
                "claim_id": claim_id,
                "state": "pending",
                "lease_expires_at": lease_expires_at,
            }
            self.authorities[key] = authority
            return deepcopy(authority)

    def release_recruitment_authority(
        self, offering_id, release_sha256, proposal_id, claim_id
    ):
        with self.lock:
            authority = self.authorities[(offering_id, release_sha256)]
            if (
                authority["state"] == "pending"
                and authority["proposal_id"] == proposal_id
                and authority["claim_id"] == claim_id
            ):
                authority["state"] = "released"
                authority["lease_expires_at"] = None

    def finalize_recruitment_authority(
        self, offering_id, release_sha256, proposal_id, claim_id
    ):
        with self.lock:
            if self.fail_finalize_authority_once:
                self.fail_finalize_authority_once = False
                raise StudyOperationsStateError(
                    "Study recruitment authority unavailable"
                )
            authority = self.authorities[(offering_id, release_sha256)]
            exact = (
                authority["proposal_id"] == proposal_id
                and authority["claim_id"] == claim_id
            )
            if authority["state"] == "finalized" and exact:
                return deepcopy(authority)
            if authority["state"] != "pending" or not exact:
                raise StudyOperationsStateError(
                    "Study recruitment authority changed"
                )
            authority["state"] = "finalized"
            authority["lease_expires_at"] = None
            return deepcopy(authority)

    def create_challenge(self, proposal_id, expected, challenge, _now):
        with self.lock:
            document = self.docs[proposal_id]
            if document["state"]["stateSha256"] != expected:
                raise StudyOperationsStateError("Study operations state changed")
            if any(
                item["idempotencyKey"] == challenge["idempotency_key"]
                for item in document["events"]
            ):
                raise StudyOperationsStateError("Study operation already applied")
            active = [
                item
                for item in document["challenges"].values()
                if item.get("consumed_at") is None
                and item.get("expires_at", 0) > _now
            ]
            if len(active) >= MAX_ACTIVE_CHALLENGES:
                raise StudyOperationsStateError(
                    "Study operation challenge capacity reached"
                )
            removable = sorted(
                (
                    item
                    for item in document["challenges"].values()
                    if item.get("consumed_at") is None
                    and item.get("expires_at", _now + 1) <= _now
                ),
                key=lambda item: item.get("issued_at", 0),
            )
            while (
                len(document["challenges"]) >= MAX_CHALLENGE_HISTORY
                and removable
            ):
                old = removable.pop(0)
                document["challenges"].pop(old["challenge_id"], None)
            if len(document["challenges"]) >= MAX_CHALLENGE_HISTORY:
                raise StudyOperationsStateError(
                    "Study operation challenge capacity reached"
                )
            document["challenges"][challenge["challenge_id"]] = deepcopy(challenge)
            return deepcopy(challenge)

    def get_challenge(self, proposal_id, challenge_id):
        with self.lock:
            try:
                return deepcopy(self.docs[proposal_id]["challenges"][challenge_id])
            except KeyError as error:
                raise StudyOperationsStateError(
                    "Study operation challenge unavailable"
                ) from error

    def idempotent_result(self, proposal_id, challenge_id, bundle_sha256):
        with self.lock:
            document = self.docs[proposal_id]
            challenge = document["challenges"][challenge_id]
            if (
                challenge.get("consumed_at") is None
                or challenge.get("bundle_sha256") != bundle_sha256
            ):
                raise StudyOperationsStateError(
                    "Study operation challenge unavailable"
                )
            event = next(
                item
                for item in document["events"]
                if item["eventSha256"] == challenge["event_sha256"]
            )
            return {"event": deepcopy(event), "state": deepcopy(document["state"])}

    def consume_transition(
        self,
        proposal_id,
        challenge_id,
        expected_state_sha256,
        expected_bundle_sha256,
        event,
        next_state,
        signature,
        now,
    ):
        with self.lock:
            if self.fail_consume_once:
                self.fail_consume_once = False
                raise StudyOperationsStateError(
                    "Study operations write unavailable"
                )
            document = self.docs[proposal_id]
            challenge = document["challenges"][challenge_id]
            if challenge.get("consumed_at") is not None:
                raise StudyOperationsStateError("Study operation challenge already used")
            if challenge["expires_at"] <= now:
                raise StudyOperationsStateError("Study operation challenge expired")
            if document["state"]["stateSha256"] != expected_state_sha256:
                raise StudyOperationsStateError("Study operations state changed")
            if challenge["bundle_sha256"] != expected_bundle_sha256:
                raise StudyOperationsStateError("Study operation bundle changed")
            for ticket in document["recruitment_tickets"].values():
                if (
                    ticket.get("finalized_at") is None
                    and ticket.get("cancelled_at") is None
                    and ticket.get("expires_at", 0) > now
                ):
                    ticket["cancelled_at"] = now
            document["events"].append(deepcopy(event))
            document["state"] = deepcopy(next_state)
            challenge["consumed_at"] = now
            challenge["event_sha256"] = event["eventSha256"]
            challenge["signature_sha256"] = hashlib.sha256(
                signature.encode("ascii")
            ).hexdigest()
            challenge["signature"] = signature
            return {"event": deepcopy(event), "state": deepcopy(next_state)}

    def reserve_recruitment(
        self, proposal_id, expected, ticket, now, maximum_tickets
    ):
        with self.lock:
            document = self.docs[proposal_id]
            if document["state"]["stateSha256"] != expected:
                raise StudyOperationsStateError("Study operations state changed")
            tickets = document["recruitment_tickets"]
            key_id = ticket["participant_binding_key_id"]
            commitment = ticket[
                "participant_binding_key_commitment_sha256"
            ]
            if document["participant_binding_key_id"] is None:
                document["participant_binding_key_id"] = key_id
                document[
                    "participant_binding_key_commitment_sha256"
                ] = commitment
            elif (
                document["participant_binding_key_id"] != key_id
                or document[
                    "participant_binding_key_commitment_sha256"
                ]
                != commitment
            ):
                raise StudyOperationsStateError(
                    "Study recruitment participant binding key changed"
                )
            for ticket_id, value in list(tickets.items()):
                if (
                    value.get("finalized_at") is None
                    and (
                        value.get("cancelled_at") is not None
                        or value.get("expires_at", now + 1) <= now
                    )
                ):
                    tickets.pop(ticket_id)
            existing = next(
                (
                    value
                    for value in tickets.values()
                    if value.get("finalized_at") is None
                    and value.get("cancelled_at") is None
                    and value.get("expires_at", 0) > now
                    and value.get("reservation_key_sha256")
                    == ticket["reservation_key_sha256"]
                ),
                None,
            )
            if existing is not None:
                return deepcopy(existing)
            if len(tickets) >= maximum_tickets:
                raise StudyOperationsStateError(
                    "Study recruitment reservation capacity reached"
                )
            if any(
                value.get("participant_binding_sha256")
                == ticket["participant_binding_sha256"]
                for value in tickets.values()
                if value.get("finalized_at") is None
            ):
                raise StudyOperationsStateError(
                    "Study recruitment participant already reserved"
                )
            tickets[ticket["ticket_id"]] = deepcopy(ticket)
            return deepcopy(ticket)

    def get_recruitment_ticket(self, proposal_id, ticket_id):
        with self.lock:
            try:
                return deepcopy(
                    self.docs[proposal_id]["recruitment_tickets"][ticket_id]
                )
            except KeyError as error:
                raise StudyOperationsStateError(
                    "Study recruitment reservation unavailable"
                ) from error

    def finalize_recruitment(
        self,
        proposal_id,
        ticket_id,
        expected_ticket_sha256,
        enrollment_sha256,
        now,
    ):
        with self.lock:
            document = self.docs[proposal_id]
            ticket = document["recruitment_tickets"][ticket_id]
            if (
                ticket["ticket_sha256"] != expected_ticket_sha256
                or ticket["cancelled_at"] is not None
                or ticket["expires_at"] <= now
                or document["state"]["stateSha256"]
                != ticket["operation_state_sha256"]
            ):
                raise StudyOperationsStateError(
                    "Study recruitment reservation unavailable"
                )
            if ticket["finalized_at"] is not None:
                if ticket["enrollment_sha256"] != enrollment_sha256:
                    raise StudyOperationsStateError(
                        "Study recruitment finalization conflict"
                    )
                return deepcopy(ticket)
            ticket["finalized_at"] = now
            ticket["enrollment_sha256"] = enrollment_sha256
            return deepcopy(ticket)

    def cancel_recruitment(self, proposal_id, ticket_id, now):
        with self.lock:
            ticket = self.docs.get(proposal_id, {}).get(
                "recruitment_tickets", {}
            ).get(ticket_id)
            if ticket is not None and ticket["finalized_at"] is None:
                ticket["cancelled_at"] = now

    def cancel_recruitment_reservation(
        self, proposal_id, reservation_key_sha256, now
    ):
        with self.lock:
            for ticket in self.docs.get(proposal_id, {}).get(
                "recruitment_tickets", {}
            ).values():
                if (
                    ticket.get("reservation_key_sha256")
                    == reservation_key_sha256
                    and ticket.get("finalized_at") is None
                ):
                    ticket["cancelled_at"] = now

    def find_by_release(self, offering_id, release_sha256, limit=2):
        assert limit == 2
        with self.lock:
            return [
                {
                    "state": deepcopy(document["state"]),
                    "participant_binding_key_id": document.get(
                        "participant_binding_key_id"
                    ),
                    "participant_binding_key_commitment_sha256": document.get(
                        "participant_binding_key_commitment_sha256"
                    ),
                }
                for document in self.docs.values()
                if document["state"]["offeringId"] == offering_id
                and document["state"]["releaseSha256"] == release_sha256
                and document["state"]["lifecycleState"] == "recruiting"
                and document["state"]["disposition"] == "current"
            ][:limit]

    def privacy_snapshot(self, proposal_id, published_on):
        with self.lock:
            return deepcopy(
                next(
                    (
                        item
                        for item in reversed(
                            self.docs[proposal_id]["privacy_snapshots"]
                        )
                        if item["publishedOn"] == published_on
                    ),
                    None,
                )
            )

    def publish_privacy_snapshot(self, proposal_id, expected, snapshot):
        with self.lock:
            document = self.docs[proposal_id]
            if document["state"]["stateSha256"] != expected:
                raise StudyOperationsStateError("Study operations state changed")
            existing = next(
                (
                    item
                    for item in reversed(document["privacy_snapshots"])
                    if item["publishedOn"] == snapshot["publishedOn"]
                ),
                None,
            )
            if existing is not None:
                return deepcopy(existing)
            document["privacy_snapshots"].append(deepcopy(snapshot))
            return deepcopy(snapshot)


def sign(account, message):
    return Account.sign_message(
        encode_defunct(text=message), account.key
    ).signature.hex()


def add_reviewed_proposal(proposals, registry, release_version, start):
    release = registry.release(RECORDING_FEASIBILITY_ID, release_version)
    workflow = StudyProposalWorkflow(
        proposals,
        clock=lambda: "2026-07-31T00:00:00Z",
        id_factory=Ids(start),
    )
    proposal = workflow.create(
        AUTHOR.address,
        payload(
            releaseVersion=release["releaseVersion"],
            releaseSha256=release["releaseSha256"],
        ),
    )
    proposal_id = proposal["proposalId"]
    revision_id = proposal["currentRevisionId"]
    revision_sha256 = proposal["currentRevisionSha256"]
    workflow.submit(proposal_id, AUTHOR.address, revision_id, revision_sha256)
    for domain, reviewer in zip(DOMAINS, REVIEWERS):
        workflow.review(
            proposal_id,
            reviewer.address,
            domain,
            "approved",
            revision_id,
            revision_sha256,
            "The generated {} evidence approves this exact revision.".format(domain),
            content_sha256({"domain": domain, "release": release_version}),
        )
    return proposal_id, revision_id, revision_sha256


def create_permit(activation, proposal_id, revision_id, revision_sha256):
    challenge = activation.create_challenge(
        proposal_id,
        OPERATOR.address,
        ORIGIN,
        revision_id,
        revision_sha256,
    )
    return activation.apply(
        proposal_id,
        OPERATOR.address,
        ORIGIN,
        challenge["challengeId"],
        sign(OPERATOR, challenge["message"]),
    )


def setup(registry=DEFAULT_STUDY_REGISTRY, challenge_ttl=300):
    proposals = ProposalDao()
    activations = ActivationDao()
    proposal_id, revision_id, revision_sha256 = add_reviewed_proposal(
        proposals, registry, "1.0.0", 0
    )
    activation = StudyActivationService(
        activations,
        proposals,
        registry,
        allowed_operators=[OPERATOR.address],
        allowed_origins=[ORIGIN],
        clock=Clock(NOW),
        nonce_factory=lambda: "generated-activation-nonce",
        id_factory=Ids(100),
    )
    permit = create_permit(
        activation, proposal_id, revision_id, revision_sha256
    )
    dao = OperationsDao()
    service = StudyOperationsService(
        dao,
        activation,
        registry,
        allowed_operators=[OPERATOR.address],
        allowed_origins=[ORIGIN],
        clock=Clock(NOW),
        challenge_ttl=challenge_ttl,
        nonce_factory=lambda: "generated-operation-nonce",
        id_factory=Ids(200),
    )
    return service, dao, activation, proposals, activations, proposal_id, permit


def transition(service, proposal_id, permit, action, index, details=None):
    status = service.status(proposal_id, permit["permitId"])
    challenge = service.create_challenge(
        proposal_id,
        OPERATOR.address,
        ORIGIN,
        permit["permitId"],
        action,
        status["state"]["stateSha256"],
        "generated-operation-{:03d}".format(index),
        details or {},
    )
    result = service.apply(
        proposal_id,
        OPERATOR.address,
        ORIGIN,
        challenge["challengeId"],
        sign(OPERATOR, challenge["message"]),
    )
    return challenge, result


def test_signed_lifecycle_replays_exactly_and_idempotently():
    service, dao, _activation, _proposals, _activations, proposal_id, permit = setup()
    expected = ["recruiting", "active", "paused", "active", "closed", "archived"]
    actions = ["recruit", "activate", "pause", "resume", "close", "archive"]
    first_challenge = None
    first_result = None
    for index, (action, target) in enumerate(zip(actions, expected), 1):
        challenge, result = transition(
            service, proposal_id, permit, action, index
        )
        assert result["state"]["lifecycleState"] == target
        assert result["state"]["eventCount"] == index
        assert result["event"]["priorStateSha256"] == challenge["bundle"][
            "priorStateSha256"
        ]
        if first_challenge is None:
            first_challenge, first_result = challenge, result

    replay = service.apply(
        proposal_id,
        OPERATOR.address,
        ORIGIN,
        first_challenge["challengeId"],
        sign(OPERATOR, first_challenge["message"]),
    )
    assert replay["event"] == first_result["event"]
    assert replay["state"]["eventCount"] == len(actions)
    assert len(dao.docs[proposal_id]["events"]) == len(actions)
    assert service.load_verified_status(proposal_id, permit["permitId"])[
        "state"
    ] == replay["state"]


def test_operation_event_uses_actual_consumption_time_and_replays_it():
    service, dao, _activation, _proposals, _activations, proposal_id, permit = setup()
    initial = service.status(proposal_id, permit["permitId"])["state"]
    challenge = service.create_challenge(
        proposal_id,
        OPERATOR.address,
        ORIGIN,
        permit["permitId"],
        "recruit",
        initial["stateSha256"],
        "generated-operation-actual-time",
        {},
    )
    service.clock.value = NOW + 17
    result = service.apply(
        proposal_id,
        OPERATOR.address,
        ORIGIN,
        challenge["challengeId"],
        sign(OPERATOR, challenge["message"]),
    )
    stored = dao.docs[proposal_id]["challenges"][challenge["challengeId"]]
    assert result["event"]["occurredAt"] == rfc3339(NOW + 17)
    assert stored["consumed_at"] == NOW + 17
    assert service.load_verified_status(proposal_id, permit["permitId"])[
        "events"
    ][0] == result["event"]


def test_only_one_proposal_can_claim_recruiting_authority_for_a_release():
    (
        service,
        dao,
        activation,
        proposals,
        _activations,
        proposal_id,
        permit,
    ) = setup()
    replacement_id, revision_id, revision_sha256 = add_reviewed_proposal(
        proposals, DEFAULT_STUDY_REGISTRY, "1.0.0", 2000
    )
    replacement_permit = create_permit(
        activation, replacement_id, revision_id, revision_sha256
    )
    replacement_state = service.status(
        replacement_id, replacement_permit["permitId"]
    )["state"]
    replacement_challenge = service.create_challenge(
        replacement_id,
        OPERATOR.address,
        ORIGIN,
        replacement_permit["permitId"],
        "recruit",
        replacement_state["stateSha256"],
        "generated-operation-competing-authority",
        {},
    )

    transition(service, proposal_id, permit, "recruit", 1)
    with pytest.raises(
        StudyOperationsError, match="study_recruitment_authority_conflict"
    ):
        service.apply(
            replacement_id,
            OPERATOR.address,
            ORIGIN,
            replacement_challenge["challengeId"],
            sign(OPERATOR, replacement_challenge["message"]),
        )
    assert dao.docs[replacement_id]["events"] == []
    assert dao.docs[replacement_id]["state"]["lifecycleState"] == "permitted"


def test_ambiguous_recruit_transition_keeps_pending_claim_for_exact_retry():
    service, dao, _activation, _proposals, _activations, proposal_id, permit = setup()
    first_state = service.status(proposal_id, permit["permitId"])["state"]
    first = service.create_challenge(
        proposal_id,
        OPERATOR.address,
        ORIGIN,
        permit["permitId"],
        "recruit",
        first_state["stateSha256"],
        "generated-operation-failed-authority",
        {},
    )
    dao.fail_consume_once = True
    signature = sign(OPERATOR, first["message"])
    with pytest.raises(
        StudyOperationsError, match="study_recruitment_transition_pending"
    ):
        service.apply(
            proposal_id,
            OPERATOR.address,
            ORIGIN,
            first["challengeId"],
            signature,
        )
    release = DEFAULT_STUDY_REGISTRY.release(RECORDING_FEASIBILITY_ID)
    authority = dao.authorities[
        (release["offeringId"], release["releaseSha256"])
    ]
    assert authority["state"] == "pending"
    assert authority["claim_id"] == first["challengeId"]

    result = service.apply(
        proposal_id,
        OPERATOR.address,
        ORIGIN,
        first["challengeId"],
        signature,
    )
    assert result["state"]["lifecycleState"] == "recruiting"
    authority = dao.authorities[
        (release["offeringId"], release["releaseSha256"])
    ]
    assert authority["state"] == "finalized"
    assert authority["proposal_id"] == proposal_id


def test_recruit_transition_crash_before_authority_finalize_recovers_on_replay():
    service, dao, _activation, _proposals, _activations, proposal_id, permit = setup()
    initial = service.status(proposal_id, permit["permitId"])["state"]
    challenge = service.create_challenge(
        proposal_id,
        OPERATOR.address,
        ORIGIN,
        permit["permitId"],
        "recruit",
        initial["stateSha256"],
        "generated-operation-finalize-recovery",
        {},
    )
    signature = sign(OPERATOR, challenge["message"])
    dao.fail_finalize_authority_once = True
    with pytest.raises(
        StudyOperationsError, match="study_recruitment_authority_pending"
    ):
        service.apply(
            proposal_id,
            OPERATOR.address,
            ORIGIN,
            challenge["challengeId"],
            signature,
        )
    release = DEFAULT_STUDY_REGISTRY.release(RECORDING_FEASIBILITY_ID)
    authority_key = (release["offeringId"], release["releaseSha256"])
    assert dao.docs[proposal_id]["state"]["lifecycleState"] == "recruiting"
    assert dao.authorities[authority_key]["state"] == "pending"

    replay = service.apply(
        proposal_id,
        OPERATOR.address,
        ORIGIN,
        challenge["challengeId"],
        signature,
    )
    assert replay["state"]["lifecycleState"] == "recruiting"
    assert dao.authorities[authority_key]["state"] == "finalized"


def test_recruit_transition_postcommit_response_loss_finalizes_and_replays():
    service, dao, _activation, _proposals, _activations, proposal_id, permit = setup()
    initial = service.status(proposal_id, permit["permitId"])["state"]
    challenge = service.create_challenge(
        proposal_id,
        OPERATOR.address,
        ORIGIN,
        permit["permitId"],
        "recruit",
        initial["stateSha256"],
        "generated-operation-lost-success-response",
        {},
    )
    signature = sign(OPERATOR, challenge["message"])
    consume = dao.consume_transition

    def commit_then_lose_response(*args, **kwargs):
        consume(*args, **kwargs)
        raise RuntimeError("study operations success response lost")

    dao.consume_transition = commit_then_lose_response
    result = service.apply(
        proposal_id,
        OPERATOR.address,
        ORIGIN,
        challenge["challengeId"],
        signature,
    )
    release = DEFAULT_STUDY_REGISTRY.release(RECORDING_FEASIBILITY_ID)
    authority_key = (release["offeringId"], release["releaseSha256"])
    assert result["state"]["lifecycleState"] == "recruiting"
    assert dao.authorities[authority_key]["state"] == "finalized"

    replay = service.apply(
        proposal_id,
        OPERATOR.address,
        ORIGIN,
        challenge["challengeId"],
        signature,
    )
    assert replay == result
    assert len(dao.docs[proposal_id]["events"]) == 1


def test_delayed_commit_after_unconsumed_read_keeps_claim_recoverable():
    service, dao, _activation, _proposals, _activations, proposal_id, permit = setup()
    initial = service.status(proposal_id, permit["permitId"])["state"]
    challenge = service.create_challenge(
        proposal_id,
        OPERATOR.address,
        ORIGIN,
        permit["permitId"],
        "recruit",
        initial["stateSha256"],
        "generated-operation-delayed-commit",
        {},
    )
    signature = sign(OPERATOR, challenge["message"])
    consume = dao.consume_transition
    delayed = {}

    def time_out_with_write_still_in_flight(*args, **kwargs):
        delayed.update({"args": args, "kwargs": kwargs})
        raise RuntimeError("study operations write timed out")

    dao.consume_transition = time_out_with_write_still_in_flight
    with pytest.raises(
        StudyOperationsError, match="study_recruitment_transition_pending"
    ):
        service.apply(
            proposal_id,
            OPERATOR.address,
            ORIGIN,
            challenge["challengeId"],
            signature,
        )
    release = DEFAULT_STUDY_REGISTRY.release(RECORDING_FEASIBILITY_ID)
    authority_key = (release["offeringId"], release["releaseSha256"])
    assert dao.docs[proposal_id]["state"]["lifecycleState"] == "permitted"
    assert dao.authorities[authority_key]["state"] == "pending"

    consume(*delayed["args"], **delayed["kwargs"])
    assert dao.docs[proposal_id]["state"]["lifecycleState"] == "recruiting"
    assert dao.authorities[authority_key]["state"] == "pending"

    replay = service.apply(
        proposal_id,
        OPERATOR.address,
        ORIGIN,
        challenge["challengeId"],
        signature,
    )
    assert replay["state"]["lifecycleState"] == "recruiting"
    assert dao.authorities[authority_key]["state"] == "finalized"
    assert len(dao.docs[proposal_id]["events"]) == 1


def test_concurrent_exact_recruit_callers_share_one_committed_result():
    service, dao, _activation, _proposals, _activations, proposal_id, permit = setup()
    initial = service.status(proposal_id, permit["permitId"])["state"]
    challenge = service.create_challenge(
        proposal_id,
        OPERATOR.address,
        ORIGIN,
        permit["permitId"],
        "recruit",
        initial["stateSha256"],
        "generated-operation-concurrent-exact",
        {},
    )
    signature = sign(OPERATOR, challenge["message"])
    consume = dao.consume_transition
    enter_consume = threading.Barrier(2)

    def consume_together(*args, **kwargs):
        enter_consume.wait()
        return consume(*args, **kwargs)

    dao.consume_transition = consume_together
    outcomes = []

    def apply():
        try:
            outcomes.append(
                service.apply(
                    proposal_id,
                    OPERATOR.address,
                    ORIGIN,
                    challenge["challengeId"],
                    signature,
                )
            )
        except Exception as error:
            outcomes.append(error)

    workers = [threading.Thread(target=apply) for _index in range(2)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(5)
        assert not worker.is_alive()

    assert len(outcomes) == 2
    assert all(isinstance(item, dict) for item in outcomes)
    assert outcomes[0] == outcomes[1]
    assert len(dao.docs[proposal_id]["events"]) == 1
    release = DEFAULT_STUDY_REGISTRY.release(RECORDING_FEASIBILITY_ID)
    authority = dao.authorities[
        (release["offeringId"], release["releaseSha256"])
    ]
    assert authority["state"] == "finalized"


def test_indeterminate_transition_keeps_pending_claim_for_exact_retry():
    service, dao, _activation, _proposals, _activations, proposal_id, permit = setup()
    initial = service.status(proposal_id, permit["permitId"])["state"]
    challenge = service.create_challenge(
        proposal_id,
        OPERATOR.address,
        ORIGIN,
        permit["permitId"],
        "recruit",
        initial["stateSha256"],
        "generated-operation-indeterminate-write",
        {},
    )
    signature = sign(OPERATOR, challenge["message"])
    consume = dao.consume_transition
    get_challenge = dao.get_challenge
    reads = 0

    def fail_before_commit(*_args, **_kwargs):
        raise RuntimeError("study operations write indeterminate")

    def fail_reconciliation_read(*args, **kwargs):
        nonlocal reads
        reads += 1
        if reads > 1:
            raise StudyOperationsStateError(
                "Study operation challenge unavailable"
            )
        return get_challenge(*args, **kwargs)

    dao.consume_transition = fail_before_commit
    dao.get_challenge = fail_reconciliation_read
    with pytest.raises(
        StudyOperationsError, match="study_recruitment_transition_pending"
    ):
        service.apply(
            proposal_id,
            OPERATOR.address,
            ORIGIN,
            challenge["challengeId"],
            signature,
        )
    release = DEFAULT_STUDY_REGISTRY.release(RECORDING_FEASIBILITY_ID)
    authority_key = (release["offeringId"], release["releaseSha256"])
    assert dao.authorities[authority_key]["state"] == "pending"
    assert dao.docs[proposal_id]["state"]["lifecycleState"] == "permitted"

    dao.consume_transition = consume
    dao.get_challenge = get_challenge
    recovered = service.apply(
        proposal_id,
        OPERATOR.address,
        ORIGIN,
        challenge["challengeId"],
        signature,
    )
    assert recovered["state"]["lifecycleState"] == "recruiting"
    assert dao.authorities[authority_key]["state"] == "finalized"


def test_expired_pending_claim_cannot_resume_after_competitor_reclaims():
    (
        service,
        dao,
        activation,
        proposals,
        _activations,
        proposal_id,
        permit,
    ) = setup()
    replacement_id, revision_id, revision_sha256 = add_reviewed_proposal(
        proposals, DEFAULT_STUDY_REGISTRY, "1.0.0", 2200
    )
    replacement_permit = create_permit(
        activation, replacement_id, revision_id, revision_sha256
    )
    initial = service.status(proposal_id, permit["permitId"])["state"]
    first = service.create_challenge(
        proposal_id,
        OPERATOR.address,
        ORIGIN,
        permit["permitId"],
        "recruit",
        initial["stateSha256"],
        "generated-operation-stalled-claim",
        {},
    )
    first_claimed = threading.Event()
    resume_first = threading.Event()
    original_begin = service._begin_recruitment_authority

    def block_after_first_claim(state, *args):
        result = original_begin(state, *args)
        if state["proposalId"] == proposal_id:
            first_claimed.set()
            assert resume_first.wait(5)
        return result

    service._begin_recruitment_authority = block_after_first_claim
    outcome = {}

    def apply_first():
        try:
            outcome["result"] = service.apply(
                proposal_id,
                OPERATOR.address,
                ORIGIN,
                first["challengeId"],
                sign(OPERATOR, first["message"]),
            )
        except Exception as error:
            outcome["error"] = error

    worker = threading.Thread(target=apply_first)
    worker.start()
    assert first_claimed.wait(5)
    release = DEFAULT_STUDY_REGISTRY.release(RECORDING_FEASIBILITY_ID)
    authority_key = (release["offeringId"], release["releaseSha256"])
    first_expiry = dao.docs[proposal_id]["challenges"][
        first["challengeId"]
    ]["expires_at"]
    assert dao.authorities[authority_key]["lease_expires_at"] == first_expiry

    service.clock.value = first_expiry
    replacement_state = service.status(
        replacement_id, replacement_permit["permitId"]
    )["state"]
    replacement = service.create_challenge(
        replacement_id,
        OPERATOR.address,
        ORIGIN,
        replacement_permit["permitId"],
        "recruit",
        replacement_state["stateSha256"],
        "generated-operation-reclaimed-authority",
        {},
    )
    winner = service.apply(
        replacement_id,
        OPERATOR.address,
        ORIGIN,
        replacement["challengeId"],
        sign(OPERATOR, replacement["message"]),
    )
    resume_first.set()
    worker.join(5)
    assert not worker.is_alive()
    assert winner["state"]["lifecycleState"] == "recruiting"
    assert isinstance(outcome.get("error"), StudyOperationsError)
    assert outcome["error"].code == "study_operation_challenge_expired"
    assert dao.docs[proposal_id]["state"]["lifecycleState"] == "permitted"
    assert dao.authorities[authority_key]["proposal_id"] == replacement_id
    assert dao.authorities[authority_key]["state"] == "finalized"


def test_late_recruit_projection_cannot_displace_finalized_authority_owner():
    (
        service,
        dao,
        activation,
        proposals,
        _activations,
        proposal_id,
        permit,
    ) = setup()
    replacement_id, revision_id, revision_sha256 = add_reviewed_proposal(
        proposals, DEFAULT_STUDY_REGISTRY, "1.0.0", 2300
    )
    replacement_permit = create_permit(
        activation, replacement_id, revision_id, revision_sha256
    )
    initial = service.status(proposal_id, permit["permitId"])["state"]
    first = service.create_challenge(
        proposal_id,
        OPERATOR.address,
        ORIGIN,
        permit["permitId"],
        "recruit",
        initial["stateSha256"],
        "generated-operation-late-projection",
        {},
    )
    consume = dao.consume_transition
    delayed = {}

    def time_out_while_write_is_in_flight(*args, **kwargs):
        delayed.update({"args": args, "kwargs": kwargs})
        raise RuntimeError("study operations write timed out")

    dao.consume_transition = time_out_while_write_is_in_flight
    with pytest.raises(
        StudyOperationsError, match="study_recruitment_transition_pending"
    ):
        service.apply(
            proposal_id,
            OPERATOR.address,
            ORIGIN,
            first["challengeId"],
            sign(OPERATOR, first["message"]),
        )
    dao.consume_transition = consume

    release = DEFAULT_STUDY_REGISTRY.release(RECORDING_FEASIBILITY_ID)
    authority_key = (release["offeringId"], release["releaseSha256"])
    first_expiry = dao.docs[proposal_id]["challenges"][
        first["challengeId"]
    ]["expires_at"]
    service.clock.value = first_expiry
    replacement_state = service.status(
        replacement_id, replacement_permit["permitId"]
    )["state"]
    replacement = service.create_challenge(
        replacement_id,
        OPERATOR.address,
        ORIGIN,
        replacement_permit["permitId"],
        "recruit",
        replacement_state["stateSha256"],
        "generated-operation-authority-winner",
        {},
    )
    winner = service.apply(
        replacement_id,
        OPERATOR.address,
        ORIGIN,
        replacement["challengeId"],
        sign(OPERATOR, replacement["message"]),
    )
    assert winner["state"]["lifecycleState"] == "recruiting"
    assert dao.authorities[authority_key]["proposal_id"] == replacement_id
    assert dao.authorities[authority_key]["state"] == "finalized"

    consume(*delayed["args"], **delayed["kwargs"])
    assert dao.docs[proposal_id]["state"]["lifecycleState"] == "recruiting"
    assert {
        item["state"]["proposalId"]
        for item in dao.find_by_release(*authority_key)
    } == {proposal_id, replacement_id}

    contract = service.recruitment_contract(
        release["offeringId"],
        release["releaseSha256"],
        service.clock.value,
        BINDING_KEY_ID,
        BINDING_COMMITMENT,
    )
    assert contract["proposalId"] == replacement_id
    for capability in (
        "recruitment",
        "collection",
        "materialization",
        "lease",
        "reminder",
    ):
        assert service.operation_allowed(
            proposal_id, permit["permitId"], capability
        ) is False
    assert service.operation_allowed(
        replacement_id, replacement_permit["permitId"], "recruitment"
    ) is True

    transition(
        service, replacement_id, replacement_permit, "activate", 2301
    )
    for capability in ("collection", "materialization", "lease", "reminder"):
        assert service.operation_allowed(
            replacement_id, replacement_permit["permitId"], capability
        ) is True


def test_exact_duplicate_crossing_expiry_does_not_release_shared_claim():
    service, dao, _activation, _proposals, _activations, proposal_id, permit = setup()
    initial = service.status(proposal_id, permit["permitId"])["state"]
    challenge = service.create_challenge(
        proposal_id,
        OPERATOR.address,
        ORIGIN,
        permit["permitId"],
        "recruit",
        initial["stateSha256"],
        "generated-operation-duplicate-expiry",
        {},
    )
    signature = sign(OPERATOR, challenge["message"])
    expires_at = dao.docs[proposal_id]["challenges"][
        challenge["challengeId"]
    ]["expires_at"]
    consume = dao.consume_transition
    first_consuming = threading.Event()
    resume_first = threading.Event()

    def hold_first_consumer(*args, **kwargs):
        first_consuming.set()
        assert resume_first.wait(5)
        return consume(*args, **kwargs)

    dao.consume_transition = hold_first_consumer
    begin = service._begin_recruitment_authority
    begin_calls = 0
    begin_lock = threading.Lock()

    def expire_after_duplicate_claim(*args, **kwargs):
        nonlocal begin_calls
        authority = begin(*args, **kwargs)
        with begin_lock:
            begin_calls += 1
            if begin_calls == 2:
                service.clock.value = expires_at
        return authority

    service._begin_recruitment_authority = expire_after_duplicate_claim
    outcomes = {}

    def apply(label):
        try:
            outcomes[label] = service.apply(
                proposal_id,
                OPERATOR.address,
                ORIGIN,
                challenge["challengeId"],
                signature,
            )
        except Exception as error:
            outcomes[label] = error

    first_worker = threading.Thread(target=apply, args=("first",))
    first_worker.start()
    assert first_consuming.wait(5)
    duplicate_worker = threading.Thread(target=apply, args=("duplicate",))
    duplicate_worker.start()
    duplicate_worker.join(5)
    assert not duplicate_worker.is_alive()

    release = DEFAULT_STUDY_REGISTRY.release(RECORDING_FEASIBILITY_ID)
    authority_key = (release["offeringId"], release["releaseSha256"])
    assert isinstance(outcomes["duplicate"], StudyOperationsError)
    assert outcomes["duplicate"].code == "study_operation_challenge_expired"
    assert dao.authorities[authority_key]["state"] == "pending"
    assert dao.authorities[authority_key]["claim_id"] == challenge["challengeId"]

    resume_first.set()
    first_worker.join(5)
    assert not first_worker.is_alive()
    assert outcomes["first"]["state"]["lifecycleState"] == "recruiting"
    assert dao.authorities[authority_key]["state"] == "finalized"
    contract = service.recruitment_contract(
        release["offeringId"],
        release["releaseSha256"],
        service.clock.value,
        BINDING_KEY_ID,
        BINDING_COMMITMENT,
    )
    assert contract["proposalId"] == proposal_id


def test_recruitment_lookup_uses_finalized_authority_among_duplicate_projections():
    service, dao, _activation, _proposals, _activations, proposal_id, permit = setup()
    transition(service, proposal_id, permit, "recruit", 1)
    release = DEFAULT_STUDY_REGISTRY.release(RECORDING_FEASIBILITY_ID)
    recruiting = dao.docs.pop(proposal_id)

    for index in range(12):
        stale = deepcopy(recruiting)
        stale["state"] = {
            **stale["state"],
            "proposalId": "study_{:x}".format(3000 + index),
            "lifecycleState": "active",
        }
        dao.docs["legacy-{}".format(index)] = stale
    dao.docs[proposal_id] = recruiting

    contract = service.recruitment_contract(
        release["offeringId"],
        release["releaseSha256"],
        NOW,
        BINDING_KEY_ID,
        BINDING_COMMITMENT,
    )
    assert contract["proposalId"] == proposal_id

    duplicate = deepcopy(recruiting)
    duplicate["state"] = {
        **duplicate["state"],
        "proposalId": "study_deadbeef",
    }
    dao.docs["duplicate-recruiting"] = duplicate
    contract = service.recruitment_contract(
        release["offeringId"],
        release["releaseSha256"],
        NOW,
        BINDING_KEY_ID,
        BINDING_COMMITMENT,
    )
    assert contract["proposalId"] == proposal_id


def test_first_transition_rechecks_permit_expiry_at_application():
    service, dao, _activation, _proposals, _activations, proposal_id, permit = setup()
    service.clock.value = NOW + 86400 - 100
    initial = service.status(proposal_id, permit["permitId"])["state"]
    challenge = service.create_challenge(
        proposal_id,
        OPERATOR.address,
        ORIGIN,
        permit["permitId"],
        "recruit",
        initial["stateSha256"],
        "generated-operation-expiring-permit",
        {},
    )
    service.clock.value = NOW + 86400 + 1
    with pytest.raises(StudyOperationsError, match="study_permit_expired"):
        service.apply(
            proposal_id,
            OPERATOR.address,
            ORIGIN,
            challenge["challengeId"],
            sign(OPERATOR, challenge["message"]),
        )
    assert dao.docs[proposal_id]["events"] == []
    assert dao.docs[proposal_id]["challenges"][challenge["challengeId"]][
        "consumed_at"
    ] is None


@pytest.mark.parametrize(
    ("action", "details"),
    (
        ("activate", {}),
        (
            "revoke",
            {
                "reasonCode": "generated-emergency",
                "evidenceSha256": "a" * 64,
            },
        ),
    ),
)
def test_operator_transition_cancels_live_recruitment_without_participant_dos(
    action, details
):
    service, dao, _activation, _proposals, _activations, proposal_id, permit = setup()
    transition(service, proposal_id, permit, "recruit", 1)
    release = DEFAULT_STUDY_REGISTRY.release(RECORDING_FEASIBILITY_ID)
    contract = service.reserve_recruitment(
        release["offeringId"],
        release["releaseSha256"],
        "b" * 64,
        BINDING_KEY_ID,
        BINDING_COMMITMENT,
        RESERVATION_KEY,
        NOW,
    )
    service.assert_recruitment_ticket(
        proposal_id,
        contract["recruitmentTicketId"],
        contract["recruitmentTicketSha256"],
        contract["participantBindingSha256"],
        contract["participantBindingKeyId"],
        contract["participantBindingKeyCommitmentSha256"],
    )
    _challenge, result = transition(
        service, proposal_id, permit, action, 2, details
    )
    stored = dao.docs[proposal_id]["recruitment_tickets"][
        contract["recruitmentTicketId"]
    ]
    assert stored["cancelled_at"] == NOW
    assert (
        result["state"]["lifecycleState"] == "active"
        if action == "activate"
        else result["state"]["disposition"] == "revoked"
    )
    with pytest.raises(
        StudyOperationsError, match="study_recruitment_ticket_cancelled"
    ):
        service.finalize_recruitment(
            proposal_id,
            contract["recruitmentTicketId"],
            contract["recruitmentTicketSha256"],
            contract["participantBindingSha256"],
            contract["participantBindingKeyId"],
            contract["participantBindingKeyCommitmentSha256"],
            "c" * 64,
            NOW,
        )


def test_finalized_recruitment_ticket_remains_replayable_after_activation():
    service, dao, _activation, _proposals, _activations, proposal_id, permit = setup()
    transition(service, proposal_id, permit, "recruit", 1)
    release = DEFAULT_STUDY_REGISTRY.release(RECORDING_FEASIBILITY_ID)
    contract = service.reserve_recruitment(
        release["offeringId"],
        release["releaseSha256"],
        "d" * 64,
        BINDING_KEY_ID,
        BINDING_COMMITMENT,
        RESERVATION_KEY,
        NOW,
    )
    finalized = service.finalize_recruitment(
        proposal_id,
        contract["recruitmentTicketId"],
        contract["recruitmentTicketSha256"],
        contract["participantBindingSha256"],
        contract["participantBindingKeyId"],
        contract["participantBindingKeyCommitmentSha256"],
        "e" * 64,
        NOW,
    )
    transition(service, proposal_id, permit, "activate", 2)
    stored = dao.docs[proposal_id]["recruitment_tickets"][
        contract["recruitmentTicketId"]
    ]
    assert stored["cancelled_at"] is None
    assert stored["finalized_at"] == NOW
    assert service.load_verified_recruitment_ticket(
        proposal_id,
        permit["permitId"],
        contract["recruitmentTicketId"],
        contract["recruitmentTicketSha256"],
        contract["participantBindingSha256"],
        contract["participantBindingKeyId"],
        contract["participantBindingKeyCommitmentSha256"],
        "e" * 64,
        NOW,
    ) == finalized


@pytest.mark.parametrize("ticket_ttl", (60, 300, 600))
def test_recruitment_ticket_uses_the_configured_bounded_ttl(ticket_ttl):
    service, _dao, _activation, _proposals, _activations, proposal_id, permit = (
        setup(challenge_ttl=ticket_ttl)
    )
    transition(service, proposal_id, permit, "recruit", 1)
    release = DEFAULT_STUDY_REGISTRY.release(RECORDING_FEASIBILITY_ID)
    contract = service.reserve_recruitment(
        release["offeringId"],
        release["releaseSha256"],
        "d" * 64,
        BINDING_KEY_ID,
        BINDING_COMMITMENT,
        RESERVATION_KEY,
        NOW,
    )
    assert contract["recruitmentTicketTtlSeconds"] == ticket_ttl
    assert (
        contract["recruitmentTicketExpiresAt"]
        - contract["recruitmentTicketIssuedAt"]
        == ticket_ttl
    )


def test_transition_matrix_is_exhaustive_and_forbidden_edges_fail_closed():
    service, _dao, _activation, _proposals, _activations, proposal_id, permit = setup()
    initial = service.status(proposal_id, permit["permitId"])["state"]
    states = ("permitted", "recruiting", "active", "paused", "closed", "archived")
    lifecycle_actions = {action for _state, action in LIFECYCLE_ACTIONS}
    for state_name in states:
        state = {**initial, "lifecycleState": state_name, "disposition": "current"}
        state["stateSha256"] = state_sha256(state)
        for action in lifecycle_actions:
            expected = LIFECYCLE_ACTIONS.get((state_name, action))
            if expected is None:
                with pytest.raises(
                    StudyOperationsError, match="study_operation_forbidden_state"
                ):
                    service._target(action, state)
            else:
                assert service._target(action, state) == expected
        for action in ALL_ACTIONS - lifecycle_actions:
            assert service._target(action, state) == state_name

    revoked = {**initial, "disposition": "revoked"}
    revoked["stateSha256"] = state_sha256(revoked)
    for action in ALL_ACTIONS - {"correct"}:
        with pytest.raises(StudyOperationsError, match="forbidden_state"):
            service._target(action, revoked)


def test_stale_state_wrong_signature_origin_and_concurrent_application_fail_closed():
    service, dao, _activation, _proposals, _activations, proposal_id, permit = setup()
    initial = service.status(proposal_id, permit["permitId"])["state"]
    with pytest.raises(StudyOperationsError, match="state_changed"):
        service.create_challenge(
            proposal_id,
            OPERATOR.address,
            ORIGIN,
            permit["permitId"],
            "recruit",
            "f" * 64,
            "generated-operation-stale",
            {},
        )
    challenge = service.create_challenge(
        proposal_id,
        OPERATOR.address,
        ORIGIN,
        permit["permitId"],
        "recruit",
        initial["stateSha256"],
        "generated-operation-concurrent",
        {},
    )
    with pytest.raises(StudyOperationsError, match="origin_forbidden"):
        service.apply(
            proposal_id,
            OPERATOR.address,
            "https://spoofed.example",
            challenge["challengeId"],
            sign(OPERATOR, challenge["message"]),
        )
    wrong = Account.from_key("0x" + "51" * 32)
    with pytest.raises(StudyOperationsError, match="signature_invalid"):
        service.apply(
            proposal_id,
            OPERATOR.address,
            ORIGIN,
            challenge["challengeId"],
            sign(wrong, challenge["message"]),
        )

    outcomes = []

    def apply():
        try:
            result = service.apply(
                proposal_id,
                OPERATOR.address,
                ORIGIN,
                challenge["challengeId"],
                sign(OPERATOR, challenge["message"]),
            )
            outcomes.append(result["state"]["lifecycleState"])
        except StudyOperationsError as error:
            outcomes.append(error.code)

    threads = [threading.Thread(target=apply) for _index in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert outcomes.count("recruiting") >= 1
    assert len(dao.docs[proposal_id]["events"]) == 1


def test_revocation_and_correction_are_append_only_and_block_recruitment():
    service, dao, _activation, _proposals, _activations, proposal_id, permit = setup()
    _challenge, recruited = transition(service, proposal_id, permit, "recruit", 1)
    first_event = deepcopy(recruited["event"])
    _challenge, corrected = transition(
        service,
        proposal_id,
        permit,
        "correct",
        2,
        {
            "targetEventSha256": first_event["eventSha256"],
            "reasonCode": "generated-correction",
            "evidenceSha256": "a" * 64,
        },
    )
    assert dao.docs[proposal_id]["events"][0] == first_event
    assert corrected["state"]["lifecycleState"] == "recruiting"
    projected = service.researcher_projection(
        proposal_id,
        permit["permitId"],
        Metrics({key: 0 for key in METRIC_KEYS}),
    )
    assert projected["hasCorrections"] is True
    _challenge, revoked = transition(
        service,
        proposal_id,
        permit,
        "revoke",
        3,
        {"reasonCode": "generated-emergency", "evidenceSha256": "b" * 64},
    )
    assert revoked["state"]["disposition"] == "revoked"
    release = DEFAULT_STUDY_REGISTRY.release(RECORDING_FEASIBILITY_ID)
    with pytest.raises(StudyOperationsError, match="study_not_recruiting"):
        service.recruitment_contract(
            release["offeringId"],
            release["releaseSha256"],
            NOW,
            BINDING_KEY_ID,
            BINDING_COMMITMENT,
        )


def test_supersession_uses_a_distinct_reviewed_permit_and_requires_renewal():
    registry = amended_registry()
    service, _dao, activation, proposals, _activations, proposal_id, permit = setup(
        registry
    )
    replacement_id, revision_id, revision_sha256 = add_reviewed_proposal(
        proposals, registry, "2.0.0", 1000
    )
    replacement = create_permit(
        activation, replacement_id, revision_id, revision_sha256
    )
    _challenge, superseded = transition(
        service,
        proposal_id,
        permit,
        "supersede",
        1,
        {
            "replacementProposalId": replacement_id,
            "replacementPermitId": replacement["permitId"],
        },
    )
    assert superseded["state"]["disposition"] == "superseded"
    assert superseded["event"]["details"]["amendment"]["renewalRequired"] is True
    assert "participantInformation" in superseded["event"]["details"][
        "amendment"
    ]["changedBindings"]
    replacement_status = service.status(replacement_id, replacement["permitId"])
    assert replacement_status["state"]["lifecycleState"] == "permitted"
    assert replacement_status["state"]["eventCount"] == 0
    assert replacement["permitSha256"] != permit["permitSha256"]
    projected = service.researcher_projection(
        proposal_id,
        permit["permitId"],
        Metrics({key: 0 for key in METRIC_KEYS}),
    )
    assert projected["disposition"] == "superseded"
    assert projected["supersededBy"]["replacementProposalId"] == replacement_id


def test_forged_rehashed_active_state_or_event_and_private_evidence_loss_fail_closed():
    service, dao, _activation, _proposals, _activations, proposal_id, permit = setup()
    _challenge, recruited = transition(service, proposal_id, permit, "recruit", 1)
    document = dao.docs[proposal_id]
    original = deepcopy(document)

    document["state"]["lifecycleState"] = "active"
    document["state"]["stateSha256"] = state_sha256(document["state"])
    with pytest.raises(StudyOperationsError, match="state_invalid"):
        service.load_verified_status(proposal_id, permit["permitId"])

    dao.docs[proposal_id] = deepcopy(original)
    event = dao.docs[proposal_id]["events"][0]
    event["targetLifecycleState"] = "active"
    event["eventSha256"] = content_sha256(
        {key: value for key, value in event.items() if key != "eventSha256"}
    )
    dao.docs[proposal_id]["state"]["lastEventSha256"] = event["eventSha256"]
    dao.docs[proposal_id]["state"]["lifecycleState"] = "active"
    dao.docs[proposal_id]["state"]["stateSha256"] = state_sha256(
        dao.docs[proposal_id]["state"]
    )
    with pytest.raises(StudyOperationsError, match="evidence_invalid"):
        service.load_verified_status(proposal_id, permit["permitId"])

    dao.docs[proposal_id] = deepcopy(original)
    event = dao.docs[proposal_id]["events"][0]
    event["occurredAt"] = "2026-08-02T00:00:00Z"
    event["eventSha256"] = content_sha256(
        {key: value for key, value in event.items() if key != "eventSha256"}
    )
    state = dao.docs[proposal_id]["state"]
    state["lastEventSha256"] = event["eventSha256"]
    state["updatedAt"] = event["occurredAt"]
    state["stateSha256"] = state_sha256(state)
    with pytest.raises(StudyOperationsError, match="evidence_invalid"):
        service.load_verified_status(proposal_id, permit["permitId"])

    dao.docs[proposal_id] = deepcopy(original)
    dao.docs[proposal_id]["challenges"].pop(recruited["event"]["challengeId"])
    with pytest.raises(StudyOperationsError, match="evidence_invalid"):
        service.load_verified_status(proposal_id, permit["permitId"])


def test_verified_replay_enforces_current_operator_allowlist():
    service, _dao, _activation, _proposals, _activations, proposal_id, permit = setup()
    transition(service, proposal_id, permit, "recruit", 1)
    wrong = Account.from_key("0x" + "61" * 32)
    service.allowed_operators = frozenset({wrong.address.lower()})
    with pytest.raises(StudyOperationsError, match="study_operator_forbidden"):
        service.load_verified_status(proposal_id, permit["permitId"])


def test_capacity_cleanup_preserves_signed_event_evidence_and_replay():
    service, dao, _activation, _proposals, _activations, proposal_id, permit = setup()
    first_challenge, _recruited = transition(
        service, proposal_id, permit, "recruit", 1
    )
    document = dao.docs[proposal_id]
    for index in range(MAX_CHALLENGE_HISTORY - 1):
        challenge_id = format(index + 1000, "032x")
        document["challenges"][challenge_id] = {
            "challenge_id": challenge_id,
            "issued_at": NOW - 1000 + index,
            "expires_at": NOW - 1,
            "consumed_at": None,
        }

    _challenge, activated = transition(
        service, proposal_id, permit, "activate", 2
    )
    assert first_challenge["challengeId"] in document["challenges"]
    assert document["challenges"][first_challenge["challengeId"]]["signature"]
    assert activated["state"]["lifecycleState"] == "active"
    assert service.load_verified_status(proposal_id, permit["permitId"])[
        "state"
    ] == activated["state"]


def test_fixed_operation_policy_blocks_paused_closed_and_noncurrent_studies():
    service, _dao, _activation, _proposals, _activations, proposal_id, permit = setup()
    assert service.operation_allowed(
        proposal_id, permit["permitId"], "collection"
    ) is False
    transition(service, proposal_id, permit, "recruit", 1)
    assert service.operation_allowed(
        proposal_id, permit["permitId"], "recruitment"
    ) is True
    transition(service, proposal_id, permit, "activate", 2)
    assert service.operation_allowed(
        proposal_id, permit["permitId"], "collection"
    ) is True
    authorized = service.load_verified_operation(
        proposal_id, permit["permitId"], "materialization"
    )
    assert authorized["state"]["lifecycleState"] == "active"
    transition(service, proposal_id, permit, "pause", 3)
    for capability in ("collection", "materialization", "lease", "reminder"):
        assert service.operation_allowed(
            proposal_id, permit["permitId"], capability
        ) is False
    with pytest.raises(StudyOperationsError, match="study_operation_not_allowed"):
        service.load_verified_operation(
            proposal_id, permit["permitId"], "materialization"
        )
    transition(service, proposal_id, permit, "close", 4)
    assert service.operation_allowed(
        proposal_id, permit["permitId"], "collection"
    ) is False

def test_task_plan_is_closed_bounded_utc_and_questionnaires_have_none():
    release = DEFAULT_STUDY_REGISTRY.release(RECORDING_FEASIBILITY_ID)
    plan = DEFAULT_STUDY_REGISTRY.task_plan(
        release["offeringId"], release["releaseVersion"], release["releaseSha256"]
    )
    starts_at, ends_at = task_window(plan, NOW)
    assert ends_at - starts_at == 14 * 86400
    assert plan["content"]["timezone"] == "UTC"
    assert plan["content"]["tasks"][0]["kind"] == "reviewed_recording"
    assert not ({"rules", "selector", "filter", "url"} & set(plan["content"]))
    with pytest.raises(StudyRegistryError, match="study_task_plan_unavailable"):
        DEFAULT_STUDY_REGISTRY.task_plan(COMMUNITY_QUESTIONNAIRE_ID)


def test_amendment_rejects_identity_drift_and_only_bound_changes_require_renewal():
    registry = amended_registry()
    old = registry.release(RECORDING_FEASIBILITY_ID, "1.0.0")
    amended = registry.release(RECORDING_FEASIBILITY_ID, "2.0.0")
    classification = classify_amendment(old, amended)
    assert classification["renewalRequired"] is True
    assert classification["changedBindings"] == ["participantInformation"]

    title_only = deepcopy(old)
    title_only["title"] = "A changed display title"
    title_only["releaseSha256"] = content_sha256(
        {key: value for key, value in title_only.items() if key != "releaseSha256"}
    )
    classification = classify_amendment(old, title_only)
    assert classification["renewalRequired"] is False
    assert classification["changedBindings"] == []

    for field in (
        "purpose",
        "survey",
        "participantInformation",
        "protocol",
        "taskPlan",
        "datasetView",
        "activationProfile",
    ):
        changed = deepcopy(old)
        changed[field] = {**changed[field], "sha256": "e" * 64}
        changed["releaseSha256"] = content_sha256({"changedBinding": field})
        classification = classify_amendment(old, changed)
        assert classification == {
            "schema": "brainstem.study-amendment-classification/v1",
            "renewalRequired": True,
            "changedBindings": [field],
        }

    for field in ("dataUnionId", "offeringId"):
        changed = {**old, field: "different-identity", "releaseSha256": "e" * 64}
        with pytest.raises(StudyOperationsError, match="supersession_invalid"):
            classify_amendment(old, changed)


class Completions:
    def __init__(self, values):
        self.values = values
        self.participants = []

    def completions(self, participant_id, _enrollment):
        self.participants.append(participant_id)
        return deepcopy(self.values)


class Metrics:
    def __init__(self, values):
        self.values = values
        self.calls = 0

    def counts(self, _operations_state):
        self.calls += 1
        return deepcopy(self.values)


def test_participant_tasks_expand_closed_plan_from_source_owned_evidence():
    service, _dao, _activation, _proposals, _activations, proposal_id, permit = setup()
    transition(service, proposal_id, permit, "recruit", 1)
    release = DEFAULT_STUDY_REGISTRY.release(RECORDING_FEASIBILITY_ID)
    contract = service.recruitment_contract(
        release["offeringId"],
        release["releaseSha256"],
        NOW,
        BINDING_KEY_ID,
        BINDING_COMMITMENT,
    )
    transition(service, proposal_id, permit, "activate", 2)
    enrollment = {
        "offeringId": release["offeringId"],
        "releaseVersion": release["releaseVersion"],
        "releaseSha256": release["releaseSha256"],
        "proposalId": contract["proposalId"],
        "permitId": contract["permitId"],
        "operationStateSha256": contract["operationStateSha256"],
        "taskPlan": contract["taskPlan"],
        "state": "active",
        "startsAt": contract["startsAt"],
        "endsAt": contract["endsAt"],
    }
    source = Completions([])
    projection = service.participant_tasks(
        enrollment, "participant-one", source
    )
    assert len(projection["tasks"]) == 14
    assert set(item["status"] for item in projection["tasks"]) == {"upcoming"}
    assert source.participants == ["participant-one"]
    serialized = repr(projection)
    assert "participant-one" not in serialized
    assert "e" * 64 not in serialized

    service.clock.value = contract["startsAt"] + 60
    source.values = [
        {
            "taskId": "resting-recording",
            "occurrence": 1,
            "capability": "brainstem.recording.resting-rr.reviewed.v1",
            "completedAt": contract["startsAt"] + 30,
            "evidenceSha256": "e" * 64,
        }
    ]
    completed = service.participant_tasks(enrollment, "participant-one", source)
    assert completed["tasks"][0]["status"] == "completed"
    assert completed["tasks"][1]["status"] == "upcoming"

    service.clock.value = contract["startsAt"] + 86400 + 60
    due = service.participant_tasks(enrollment, "participant-one", source)
    assert due["tasks"][1]["status"] == "due"

    service.clock.value = contract["startsAt"] + 2 * 86400
    missed = service.participant_tasks(enrollment, "participant-one", source)
    assert missed["tasks"][1]["status"] == "missed"
    assert missed["tasks"][2]["status"] == "due"
    transition(service, proposal_id, permit, "pause", 3)
    closed = service.participant_tasks(enrollment, "participant-one", source)
    assert closed["tasks"][0]["status"] == "completed"
    assert all(
        item["status"] in {"completed", "closed"} for item in closed["tasks"]
    )


def test_participant_task_completion_evidence_is_strict_and_fail_closed():
    service, _dao, _activation, _proposals, _activations, proposal_id, permit = setup()
    transition(service, proposal_id, permit, "recruit", 1)
    release = DEFAULT_STUDY_REGISTRY.release(RECORDING_FEASIBILITY_ID)
    contract = service.recruitment_contract(
        release["offeringId"],
        release["releaseSha256"],
        NOW,
        BINDING_KEY_ID,
        BINDING_COMMITMENT,
    )
    enrollment = {
        "offeringId": release["offeringId"],
        "releaseVersion": release["releaseVersion"],
        "releaseSha256": release["releaseSha256"],
        "proposalId": proposal_id,
        "permitId": permit["permitId"],
        "taskPlan": contract["taskPlan"],
        "state": "active",
        "startsAt": contract["startsAt"],
        "endsAt": contract["endsAt"],
    }
    invalid = Completions(
        [
            {
                "taskId": "resting-recording",
                "occurrence": 1,
                "capability": "client.claimed-completion",
                "completedAt": contract["startsAt"] + 60,
                "evidenceSha256": "e" * 64,
            }
        ]
    )
    with pytest.raises(StudyOperationsError, match="evidence_invalid"):
        service.participant_tasks(enrollment, "participant-one", invalid)


def test_researcher_projection_uses_fixed_bands_and_one_snapshot_per_utc_day():
    service, dao, _activation, _proposals, _activations, proposal_id, permit = setup()
    metrics = Metrics(
        {
            "recruitment": 19,
            "adherence": 20,
            "dataQuality": 50,
            "resultAvailability": 100,
        }
    )
    first = service.researcher_projection(
        proposal_id, permit["permitId"], metrics
    )
    assert first["bands"] == {
        "recruitment": "under_disclosure_floor",
        "adherence": "20_49",
        "dataQuality": "50_99",
        "resultAvailability": "100_plus",
    }
    metrics.values = {key: 1000 for key in metrics.values}
    assert service.researcher_projection(
        proposal_id, permit["permitId"], metrics
    ) == first
    assert metrics.calls == 1
    stored = dao.docs[proposal_id]["privacy_snapshots"][0]
    assert set(stored) == {"schema", "publishedOn", "stateSha256", "bands"}
    assert stored["bands"] == first["bands"]

    service.clock.value += 86400
    next_day = service.researcher_projection(
        proposal_id, permit["permitId"], metrics
    )
    assert next_day["publishedOn"] != first["publishedOn"]
    assert set(next_day["bands"].values()) == {"100_plus"}
    assert metrics.calls == 2


def test_daily_snapshot_explicitly_marks_state_change_without_refreshing_counts():
    service, _dao, _activation, _proposals, _activations, proposal_id, permit = setup()
    metrics = Metrics({key: 19 for key in METRIC_KEYS})
    permitted = service.researcher_projection(
        proposal_id, permit["permitId"], metrics
    )
    assert permitted["snapshotCurrent"] is True
    transition(service, proposal_id, permit, "recruit", 1)
    recruiting = service.researcher_projection(
        proposal_id, permit["permitId"], metrics
    )
    assert recruiting["lifecycleState"] == "recruiting"
    assert recruiting["bands"] == permitted["bands"]
    assert recruiting["stateSha256"] != recruiting["snapshotStateSha256"]
    assert recruiting["snapshotCurrent"] is False
    assert metrics.calls == 1


@pytest.mark.parametrize(
    "value,expected",
    [
        (0, "none"),
        (1, "under_disclosure_floor"),
        (19, "under_disclosure_floor"),
        (20, "20_49"),
        (49, "20_49"),
        (50, "50_99"),
        (99, "50_99"),
        (100, "100_plus"),
    ],
)
def test_privacy_band_boundaries(value, expected):
    assert privacy_band(value) == expected


def test_metrics_source_aggregates_matching_enrollments_without_returning_rows():
    release = DEFAULT_STUDY_REGISTRY.release(RECORDING_FEASIBILITY_ID)
    operations_state = {
        "proposalId": "study_generated",
        "permitId": "permit_" + "1" * 32,
        "offeringId": release["offeringId"],
        "releaseSha256": release["releaseSha256"],
    }

    def enrollment(state="active", **changes):
        value = {
            "proposalId": operations_state["proposalId"],
            "permitId": operations_state["permitId"],
            "offeringId": operations_state["offeringId"],
            "releaseSha256": operations_state["releaseSha256"],
            "state": state,
        }
        value.update(changes)
        value["enrollmentSha256"] = content_sha256(value)
        return value

    class StudyDao:
        @staticmethod
        def generic_operations_metric_states(limit):
            assert limit == 10001
            return [
                {
                    "user_id": "verified-participant",
                    "offerings": {
                        release["offeringId"]: {
                            "enrollment": enrollment(
                                participantSecret="must-not-leave-source"
                            )
                        }
                    }
                },
                {
                    "user_id": "withdrawn-participant",
                    "offerings": {
                        release["offeringId"]: {
                            "enrollment": enrollment("withdrawn")
                        }
                    }
                },
                {
                    "user_id": "renewal-participant",
                    "offerings": {
                        release["offeringId"]: {
                            "enrollment": enrollment("renewal_required")
                        }
                    }
                },
                {
                    "user_id": "forged-participant",
                    "offerings": {
                        release["offeringId"]: {
                            "enrollment": {
                                **enrollment(),
                                "enrollmentSha256": "f" * 64,
                            }
                        }
                    }
                },
            ]

    calls = []

    def verify(user_id, offering_id, row):
        calls.append(user_id)
        if user_id != "verified-participant":
            return None
        return row["offerings"][offering_id]["enrollment"]

    counts = StudyOperationsMetricsSource(StudyDao(), verify).counts(
        operations_state
    )
    assert counts == {
        "recruitment": 1,
        "adherence": 0,
        "dataQuality": 0,
        "resultAvailability": 0,
    }
    assert calls == [
        "verified-participant",
        "withdrawn-participant",
        "renewal-participant",
        "forged-participant",
    ]
    assert "participantSecret" not in counts


def test_metrics_source_fails_closed_above_bounded_row_limit():
    class StudyDao:
        @staticmethod
        def generic_operations_metric_states(_limit):
            return [{}] * 10001

    with pytest.raises(StudyOperationsError, match="metrics_capacity"):
        StudyOperationsMetricsSource(StudyDao(), lambda *_args: None).counts(
            {
                "proposalId": "study_generated",
                "permitId": "permit_" + "1" * 32,
                "offeringId": RECORDING_FEASIBILITY_ID,
                "releaseSha256": "f" * 64,
            }
        )


def test_metrics_source_requires_authoritative_enrollment_verifier():
    with pytest.raises(StudyOperationsError, match="metrics_unavailable"):
        StudyOperationsMetricsSource(object()).counts({})
