from copy import deepcopy

import pytest

from dao.base_dao import DBResultError
from dao.study_operations_dao import (
    MAX_CHALLENGE_HISTORY,
    MAX_PRIVACY_SNAPSHOTS,
    MAX_RECRUITMENT_TICKETS,
    StudyOperationsDao,
    StudyOperationsStateError,
)


PROPOSAL_ID = "study_1"
STATE_SHA256 = "a" * 64
BUNDLE_SHA256 = "b" * 64


@pytest.fixture
def dao(monkeypatch):
    current = StudyOperationsDao()
    documents = {}

    def get_if_exists(doc_id):
        document = documents.get(doc_id)
        return document is not None, deepcopy(document)

    def save(doc_id, value):
        if doc_id in documents:
            raise DBResultError("generated", "duplicate")
        documents[doc_id] = deepcopy(value)

    def mutate_doc(doc_id, mutator):
        updated = mutator(deepcopy(documents[doc_id]))
        if updated is not None:
            documents[doc_id] = deepcopy(updated)

    monkeypatch.setattr(current, "get_if_exists", get_if_exists)
    monkeypatch.setattr(current, "save", save)
    monkeypatch.setattr(current, "mutate_doc", mutate_doc)
    return current, documents


def state(sha256=STATE_SHA256):
    return {
        "proposalId": PROPOSAL_ID,
        "offeringId": "brainstem.generated-study",
        "releaseSha256": "c" * 64,
        "stateSha256": sha256,
        "lifecycleState": "recruiting",
        "disposition": "current",
    }


def challenge(identifier="1" * 32, expires_at=200):
    return {
        "challenge_id": identifier,
        "idempotency_key": "test-operation",
        "bundle_sha256": BUNDLE_SHA256,
        "issued_at": 100,
        "expires_at": expires_at,
        "consumed_at": None,
    }


def event():
    return {
        "eventId": "operation_" + "2" * 32,
        "idempotencyKey": "test-operation",
        "eventSha256": "d" * 64,
    }


def recruitment_ticket(
    identifier="3" * 32,
    expires_at=200,
    participant_binding="5" * 64,
    participant_binding_key_id="binding-v1",
    participant_binding_key_commitment="6" * 64,
    reservation_key="7" * 64,
):
    return {
        "schema": "brainstem.study-recruitment-ticket/v3",
        "ticket_id": identifier,
        "ticket_sha256": "4" * 64,
        "participant_binding_key_id": participant_binding_key_id,
        "participant_binding_key_commitment_sha256": (
            participant_binding_key_commitment
        ),
        "participant_binding_sha256": participant_binding,
        "reservation_key_sha256": reservation_key,
        "operation_state_sha256": STATE_SHA256,
        "issued_at": 100,
        "expires_at": expires_at,
        "finalized_at": None,
        "enrollment_sha256": None,
        "cancelled_at": None,
    }


def test_transition_consumes_challenge_and_changes_state_in_one_cas(dao):
    current, documents = dao
    current.ensure_state(PROPOSAL_ID, state())
    current.create_challenge(PROPOSAL_ID, STATE_SHA256, challenge(), 100)
    next_state = state("e" * 64)
    result = current.consume_transition(
        PROPOSAL_ID,
        "1" * 32,
        STATE_SHA256,
        BUNDLE_SHA256,
        event(),
        next_state,
        "0x" + "3" * 130,
        101,
    )
    document = documents[current._doc_id(PROPOSAL_ID)]
    stored_challenge = document["challenges"]["1" * 32]
    assert result == {"event": event(), "state": next_state}
    assert document["state"] == next_state
    assert document["events"] == [event()]
    assert stored_challenge["consumed_at"] == 101
    assert stored_challenge["event_sha256"] == event()["eventSha256"]
    assert stored_challenge["signature"] == "0x" + "3" * 130
    assert len(stored_challenge["signature_sha256"]) == 64


def test_stale_state_and_duplicate_idempotency_fail_closed(dao):
    current, documents = dao
    current.ensure_state(PROPOSAL_ID, state())
    with pytest.raises(StudyOperationsStateError, match="state changed"):
        current.create_challenge(
            PROPOSAL_ID, "f" * 64, challenge(), 100
        )
    documents[current._doc_id(PROPOSAL_ID)]["events"].append(event())
    with pytest.raises(StudyOperationsStateError, match="already applied"):
        current.create_challenge(
            PROPOSAL_ID, STATE_SHA256, challenge(), 100
        )


def test_capacity_cleanup_never_evicts_consumed_signature_evidence(dao):
    current, documents = dao
    current.ensure_state(PROPOSAL_ID, state())
    first = challenge()
    current.create_challenge(PROPOSAL_ID, STATE_SHA256, first, 100)
    next_state = state("e" * 64)
    current.consume_transition(
        PROPOSAL_ID,
        first["challenge_id"],
        STATE_SHA256,
        BUNDLE_SHA256,
        event(),
        next_state,
        "0x" + "3" * 130,
        101,
    )
    document = documents[current._doc_id(PROPOSAL_ID)]
    for index in range(MAX_CHALLENGE_HISTORY - 1):
        identifier = format(index + 100, "032x")
        document["challenges"][identifier] = {
            **challenge(identifier, expires_at=99),
            "idempotency_key": "expired-operation-{:03d}".format(index),
        }
    newest = {
        **challenge("f" * 32, expires_at=300),
        "idempotency_key": "generated-operation-newest",
    }
    current.create_challenge(
        PROPOSAL_ID, next_state["stateSha256"], newest, 200
    )
    stored = documents[current._doc_id(PROPOSAL_ID)]["challenges"]
    assert len(stored) == MAX_CHALLENGE_HISTORY
    assert first["challenge_id"] in stored
    assert stored[first["challenge_id"]]["signature"] == "0x" + "3" * 130
    assert newest["challenge_id"] in stored

    for value in stored.values():
        if value.get("consumed_at") is None:
            value["consumed_at"] = 150
    with pytest.raises(StudyOperationsStateError, match="capacity"):
        current.create_challenge(
            PROPOSAL_ID,
            next_state["stateSha256"],
            {
                **challenge("9" * 32, expires_at=400),
                "idempotency_key": "generated-operation-over-capacity",
            },
            200,
        )


def test_transition_atomically_cancels_live_recruitment_but_preserves_finalized(dao):
    current, documents = dao
    current.ensure_state(PROPOSAL_ID, state())
    live = recruitment_ticket()
    finalized = {
        **recruitment_ticket("6" * 32, reservation_key="9" * 64),
        "participant_binding_sha256": "8" * 64,
        "finalized_at": 101,
        "enrollment_sha256": "7" * 64,
    }
    current.reserve_recruitment(PROPOSAL_ID, STATE_SHA256, live, 100)
    current.reserve_recruitment(PROPOSAL_ID, STATE_SHA256, finalized, 100)
    current.create_challenge(PROPOSAL_ID, STATE_SHA256, challenge(), 100)
    next_state = {
        **state("e" * 64),
        "lifecycleState": "active",
    }
    current.consume_transition(
        PROPOSAL_ID,
        "1" * 32,
        STATE_SHA256,
        BUNDLE_SHA256,
        event(),
        next_state,
        "0x" + "3" * 130,
        102,
    )
    tickets = documents[current._doc_id(PROPOSAL_ID)]["recruitment_tickets"]
    assert tickets[live["ticket_id"]]["cancelled_at"] == 102
    assert tickets[finalized["ticket_id"]] == finalized


def test_recruitment_finalization_is_exact_idempotent_and_keeps_evidence(dao):
    current, documents = dao
    current.ensure_state(PROPOSAL_ID, state())
    ticket = recruitment_ticket()
    current.reserve_recruitment(PROPOSAL_ID, STATE_SHA256, ticket, 100)
    first = current.finalize_recruitment(
        PROPOSAL_ID,
        ticket["ticket_id"],
        ticket["ticket_sha256"],
        "8" * 64,
        101,
    )
    replay = current.finalize_recruitment(
        PROPOSAL_ID,
        ticket["ticket_id"],
        ticket["ticket_sha256"],
        "8" * 64,
        150,
    )
    assert replay == first
    assert first["finalized_at"] == 101
    assert current.get_recruitment_ticket(
        PROPOSAL_ID, ticket["ticket_id"]
    ) == first
    with pytest.raises(StudyOperationsStateError, match="conflict"):
        current.finalize_recruitment(
            PROPOSAL_ID,
            ticket["ticket_id"],
            ticket["ticket_sha256"],
            "9" * 64,
            151,
        )
    assert len(
        documents[current._doc_id(PROPOSAL_ID)]["recruitment_tickets"]
    ) == 1


def test_recruitment_capacity_counts_unique_participants_not_renewals(dao):
    current, documents = dao
    current.ensure_state(PROPOSAL_ID, state())
    first = recruitment_ticket()
    current.reserve_recruitment(
        PROPOSAL_ID, STATE_SHA256, first, 100, maximum_tickets=1
    )
    current.finalize_recruitment(
        PROPOSAL_ID,
        first["ticket_id"],
        first["ticket_sha256"],
        "8" * 64,
        101,
    )

    renewal = recruitment_ticket("6" * 32, reservation_key="8" * 64)
    current.reserve_recruitment(
        PROPOSAL_ID, STATE_SHA256, renewal, 102, maximum_tickets=1
    )
    current.finalize_recruitment(
        PROPOSAL_ID,
        renewal["ticket_id"],
        renewal["ticket_sha256"],
        "9" * 64,
        103,
    )
    assert len(
        documents[current._doc_id(PROPOSAL_ID)]["recruitment_tickets"]
    ) == 2

    different_participant = recruitment_ticket(
        "7" * 32, participant_binding="a" * 64
    )
    with pytest.raises(StudyOperationsStateError, match="capacity"):
        current.reserve_recruitment(
            PROPOSAL_ID,
            STATE_SHA256,
            different_participant,
            104,
            maximum_tickets=1,
        )


def test_durable_evidence_cap_preserves_the_last_promised_seat(dao):
    current, documents = dao
    current.ensure_state(PROPOSAL_ID, state())
    first = {
        **recruitment_ticket(),
        "finalized_at": 101,
        "enrollment_sha256": "8" * 64,
    }

    class SparseTickets(dict):
        def __len__(self):
            return MAX_RECRUITMENT_TICKETS - 2 + super().__len__()

    documents[current._doc_id(PROPOSAL_ID)]["recruitment_tickets"] = (
        SparseTickets({first["ticket_id"]: first})
    )
    renewal = recruitment_ticket("6" * 32, reservation_key="8" * 64)
    with pytest.raises(
        StudyOperationsStateError, match="evidence capacity"
    ):
        current.reserve_recruitment(
            PROPOSAL_ID,
            STATE_SHA256,
            renewal,
            102,
            maximum_tickets=2,
        )

    last_seat = recruitment_ticket(
        "7" * 32,
        participant_binding="a" * 64,
        reservation_key="9" * 64,
    )
    assert current.reserve_recruitment(
        PROPOSAL_ID,
        STATE_SHA256,
        last_seat,
        102,
        maximum_tickets=2,
    ) == last_seat
    assert len(
        documents[current._doc_id(PROPOSAL_ID)]["recruitment_tickets"]
    ) == MAX_RECRUITMENT_TICKETS


def test_recruitment_counts_live_signed_reservations_toward_capacity(dao):
    current, _documents = dao
    current.ensure_state(PROPOSAL_ID, state())
    current.reserve_recruitment(
        PROPOSAL_ID,
        STATE_SHA256,
        recruitment_ticket(),
        100,
        maximum_tickets=2,
    )
    current.reserve_recruitment(
        PROPOSAL_ID,
        STATE_SHA256,
        recruitment_ticket(
            "6" * 32,
            participant_binding="6" * 64,
            reservation_key="8" * 64,
        ),
        100,
        maximum_tickets=2,
    )
    with pytest.raises(StudyOperationsStateError, match="capacity"):
        current.reserve_recruitment(
            PROPOSAL_ID,
            STATE_SHA256,
            recruitment_ticket(
                "7" * 32,
                participant_binding="7" * 64,
                reservation_key="9" * 64,
            ),
            100,
            maximum_tickets=2,
        )


def test_recruitment_reservation_retry_reuses_and_cancels_by_stable_key(dao):
    current, documents = dao
    current.ensure_state(PROPOSAL_ID, state())
    first = recruitment_ticket()
    assert current.reserve_recruitment(
        PROPOSAL_ID, STATE_SHA256, first, 100
    ) == first

    retry = recruitment_ticket("6" * 32)
    assert current.reserve_recruitment(
        PROPOSAL_ID, STATE_SHA256, retry, 110
    ) == first
    tickets = documents[current._doc_id(PROPOSAL_ID)]["recruitment_tickets"]
    assert set(tickets) == {first["ticket_id"]}

    current.cancel_recruitment_reservation(
        PROPOSAL_ID, first["reservation_key_sha256"], 111
    )
    assert documents[current._doc_id(PROPOSAL_ID)]["recruitment_tickets"][
        first["ticket_id"]
    ]["cancelled_at"] == 111


def test_participant_binding_key_is_immutable_for_a_proposal_release(dao):
    current, documents = dao
    current.ensure_state(PROPOSAL_ID, state())
    first = recruitment_ticket()
    current.reserve_recruitment(PROPOSAL_ID, STATE_SHA256, first, 100)
    current.finalize_recruitment(
        PROPOSAL_ID,
        first["ticket_id"],
        first["ticket_sha256"],
        "8" * 64,
        101,
    )
    assert documents[current._doc_id(PROPOSAL_ID)][
        "participant_binding_key_id"
    ] == "binding-v1"

    drifted = recruitment_ticket(
        "6" * 32,
        participant_binding="6" * 64,
        participant_binding_key_id="binding-v2",
    )
    with pytest.raises(StudyOperationsStateError, match="binding key changed"):
        current.reserve_recruitment(
            PROPOSAL_ID, STATE_SHA256, drifted, 102
        )

    same_id_changed_secret = recruitment_ticket(
        "7" * 32,
        participant_binding="7" * 64,
        participant_binding_key_commitment="8" * 64,
        reservation_key="9" * 64,
    )
    with pytest.raises(StudyOperationsStateError, match="binding key changed"):
        current.reserve_recruitment(
            PROPOSAL_ID, STATE_SHA256, same_id_changed_secret, 102
        )
    assert len(
        documents[current._doc_id(PROPOSAL_ID)]["recruitment_tickets"]
    ) == 1


def test_recruitment_authority_claim_is_unique_and_idempotent(dao):
    current, _documents = dao
    offering_id = "brainstem.generated-study"
    release_sha256 = "c" * 64
    permit_id = "permit_" + "1" * 32
    claim_id = "2" * 32

    first = current.claim_recruitment_authority(
        offering_id,
        release_sha256,
        PROPOSAL_ID,
        permit_id,
        claim_id,
        100,
        200,
    )
    assert current.claim_recruitment_authority(
        offering_id,
        release_sha256,
        PROPOSAL_ID,
        permit_id,
        claim_id,
        101,
        200,
    ) == first
    with pytest.raises(StudyOperationsStateError, match="already claimed"):
        current.claim_recruitment_authority(
            offering_id,
            release_sha256,
            "study_2",
            "permit_" + "3" * 32,
            "4" * 32,
            199,
            300,
        )
    replacement = current.claim_recruitment_authority(
        offering_id,
        release_sha256,
        "study_2",
        "permit_" + "3" * 32,
        "4" * 32,
        200,
        300,
        replace_claim_id=claim_id,
    )
    assert replacement["proposal_id"] == "study_2"
    assert replacement["state"] == "pending"
    finalized = current.finalize_recruitment_authority(
        offering_id, release_sha256, "study_2", "4" * 32
    )
    assert finalized["state"] == "finalized"
    current.release_recruitment_authority(
        offering_id, release_sha256, "study_2", "4" * 32
    )
    assert current.get_recruitment_authority(
        offering_id, release_sha256
    )["state"] == "finalized"


def test_recruitment_lookup_filters_authority_before_its_limit(dao, monkeypatch):
    current, _documents = dao
    captured = {}

    def find(query):
        captured.update(query)
        return {"result": [{"state": state()}]}

    monkeypatch.setattr(current, "query_data", find)
    assert current.find_by_release(
        "brainstem.generated-study", "c" * 64
    ) == [{"state": state()}]
    assert captured["selector"] == {
        "document_type": "brainstem_study_operations",
        "state.offeringId": "brainstem.generated-study",
        "state.releaseSha256": "c" * 64,
        "state.lifecycleState": "recruiting",
        "state.disposition": "current",
    }
    assert captured["limit"] == 2


def test_privacy_snapshots_are_daily_append_only_and_state_cas_bound(dao):
    current, documents = dao
    current.ensure_state(PROPOSAL_ID, state())
    first = {
        "schema": "brainstem.study-privacy-snapshot/v1",
        "publishedOn": "2026-07-31",
        "stateSha256": STATE_SHA256,
        "bands": {"recruitment": "under_disclosure_floor"},
    }
    assert current.publish_privacy_snapshot(
        PROPOSAL_ID, STATE_SHA256, first
    ) == first
    replacement = {**first, "bands": {"recruitment": "100_plus"}}
    assert current.publish_privacy_snapshot(
        PROPOSAL_ID, STATE_SHA256, replacement
    ) == first
    assert current.privacy_snapshot(PROPOSAL_ID, "2026-07-31") == first
    assert documents[current._doc_id(PROPOSAL_ID)]["privacy_snapshots"] == [first]
    with pytest.raises(StudyOperationsStateError, match="state changed"):
        current.publish_privacy_snapshot(
            PROPOSAL_ID,
            "f" * 64,
            {**first, "publishedOn": "2026-08-01"},
        )

    snapshots = documents[current._doc_id(PROPOSAL_ID)]["privacy_snapshots"]
    for index in range(1, MAX_PRIVACY_SNAPSHOTS):
        snapshots.append({**first, "publishedOn": "day-{}".format(index)})
    with pytest.raises(StudyOperationsStateError, match="capacity"):
        current.publish_privacy_snapshot(
            PROPOSAL_ID,
            STATE_SHA256,
            {**first, "publishedOn": "2027-01-01"},
        )
