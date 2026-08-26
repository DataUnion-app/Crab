from copy import deepcopy
import hashlib
import threading

import pytest
from eth_account import Account
from eth_account.messages import encode_defunct

from commands.dataunions.brainstem.generic_study_service import (
    _enrollment_sha256,
    _participant_binding,
    _participant_binding_secret_commitment,
    create_response,
    GenericStudyService,
    GenericStudyServiceError,
    MAX_ACTION_HISTORY,
    validate_response,
)
from commands.dataunions.brainstem.study_registry import (
    APDET_DIAGNOSIS_QUESTIONNAIRE_ID,
    COMMUNITY_QUESTIONNAIRE_ID,
    DEFAULT_STUDY_REGISTRY,
    RECORDING_FEASIBILITY_ID,
)
from commands.dataunions.brainstem.study_operations import StudyOperationsError
from tests.commands.metadata.test_brainstem_study_registry import amended_registry


NOW = 1785595200
ORIGIN = "https://desci.example"
ACCOUNT_ONE = Account.from_key("0x" + "21" * 32)
ACCOUNT_TWO = Account.from_key("0x" + "22" * 32)
COMMUNITY_ANSWER = {"health_priority": "sleep"}
STUDY_ANSWER = {
    "adult_status": "yes",
    "chronic_condition_status": "unsure",
    "clinician_confirmation_status": "prefer_not_to_say",
}
BINDING_SECRET = "1" * 64
BINDING_KEY_ID = "test-binding-v1"


class Auth:
    def __init__(self, participant, account):
        self.participant = participant
        self.account = account

    def authenticate(self, token, origin):
        assert token == "session"
        assert origin == ORIGIN
        return (
            "session-id",
            {},
            {
                "_id": self.participant,
                "public_address": self.account.address,
                "usage_flag": "ACCEPTED",
                "guidelines_acceptance_flag": "ACCEPTED",
            },
        )


class Dao:
    def __init__(self):
        self.states = {}

    def get_state(self, user_id):
        return deepcopy(self.states.get(user_id))

    def mutate_state(self, user_id, mutator):
        value = deepcopy(
            self.states.get(user_id)
            or {
                "document_type": "brainstem_study_participant_state",
                "user_id": user_id,
            }
        )
        value = mutator(value)
        self.states[user_id] = deepcopy(value)
        return deepcopy(value)


class LockedDao(Dao):
    def __init__(self):
        super().__init__()
        self.lock = threading.RLock()

    def get_state(self, user_id):
        with self.lock:
            return super().get_state(user_id)

    def mutate_state(self, user_id, mutator):
        with self.lock:
            return super().mutate_state(user_id, mutator)


class FailingDao(Dao):
    def __init__(self):
        super().__init__()
        self.fail_next_mutation = False

    def mutate_state(self, user_id, mutator):
        if self.fail_next_mutation:
            self.fail_next_mutation = False
            raise RuntimeError("participant store unavailable")
        return super().mutate_state(user_id, mutator)


class ClearFailingDao(Dao):
    def __init__(self):
        super().__init__()
        self.fail_clear_once = True

    def mutate_state(self, user_id, mutator):
        if self.fail_clear_once and mutator.__name__ == "clear":
            self.fail_clear_once = False
            raise RuntimeError("participant challenge clear unavailable")
        return super().mutate_state(user_id, mutator)


class Operations:
    def __init__(
        self,
        registry=DEFAULT_STUDY_REGISTRY,
        renewal_required=False,
        clock=lambda: NOW,
        ticket_ttl=300,
    ):
        self.registry = registry
        self.renewal_required = renewal_required
        self.clock = clock
        self.task_calls = []
        self.tickets = {}
        self.ticket_counter = 0
        self.fail_finalize_once = False
        self.cancel_on_finalize = False
        self.fail_cancel = False
        self.ticket_ttl = ticket_ttl
        self.pinned_binding_key_id = None
        self.pinned_binding_key_commitment = None
        self.participant_binding_secret = BINDING_SECRET
        self.participant_binding_key_id = BINDING_KEY_ID

    def recruitment_contract(
        self,
        offering_id,
        release_sha256,
        now,
        participant_binding_key_id,
        participant_binding_key_commitment_sha256,
    ):
        if (
            self.pinned_binding_key_id is not None
            and (
                self.pinned_binding_key_id != participant_binding_key_id
                or self.pinned_binding_key_commitment
                != participant_binding_key_commitment_sha256
            )
        ):
            raise StudyOperationsError(
                "study_recruitment_authority_changed", 409
            )
        release = self.registry.release(offering_id, release_sha256=release_sha256)
        task_plan = self.registry.task_plan(
            offering_id, release["releaseVersion"], release_sha256
        )
        start = now - (now % 86400)
        if now != start:
            start += 86400
        days = max(
            task["windowEndDay"] for task in task_plan["content"]["tasks"]
        )
        return {
            "proposalId": "study_1234",
            "permitId": "permit_" + "1" * 32,
            "operationStateSha256": "2" * 64,
            "taskPlan": deepcopy(release["taskPlan"]),
            "startsAt": start,
            "endsAt": start + days * 86400,
            "participantBindingKeyId": participant_binding_key_id,
            "participantBindingKeyCommitmentSha256": (
                participant_binding_key_commitment_sha256
            ),
            "recruitmentTicketTtlSeconds": self.ticket_ttl,
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
        contract = self.recruitment_contract(
            offering_id,
            release_sha256,
            consumed_at,
            participant_binding_key_id,
            participant_binding_key_commitment_sha256,
        )
        existing = next(
            (
                value
                for value in self.tickets.values()
                if value["recruitmentReservationKeySha256"]
                == reservation_key_sha256
                and value["finalized_at"] is None
                and value["cancelled_at"] is None
                and value["recruitmentTicketExpiresAt"] > consumed_at
            ),
            None,
        )
        if existing is not None:
            return {
                key: deepcopy(value)
                for key, value in existing.items()
                if key
                not in {"finalized_at", "enrollment_sha256", "cancelled_at"}
            }
        self.pinned_binding_key_id = participant_binding_key_id
        self.pinned_binding_key_commitment = (
            participant_binding_key_commitment_sha256
        )
        self.ticket_counter += 1
        ticket_id = format(self.ticket_counter, "032x")
        ticket_sha256 = format(self.ticket_counter + 10, "064x")
        value = {
            **contract,
            "participantBindingSha256": participant_binding_sha256,
            "recruitmentReservationKeySha256": reservation_key_sha256,
            "recruitmentTicketId": ticket_id,
            "recruitmentTicketSha256": ticket_sha256,
            "recruitmentTicketIssuedAt": consumed_at,
            "recruitmentTicketExpiresAt": consumed_at + self.ticket_ttl,
        }
        self.tickets[ticket_id] = {
            **deepcopy(value),
            "finalized_at": None,
            "enrollment_sha256": None,
            "cancelled_at": None,
        }
        return value

    def assert_recruitment_ticket(
        self,
        proposal_id,
        ticket_id,
        ticket_sha256,
        participant_binding_sha256,
        participant_binding_key_id,
        participant_binding_key_commitment_sha256,
    ):
        ticket = self.tickets[ticket_id]
        assert ticket["proposalId"] == proposal_id
        assert ticket["recruitmentTicketSha256"] == ticket_sha256
        assert ticket["participantBindingKeyId"] == participant_binding_key_id
        assert (
            ticket["participantBindingKeyCommitmentSha256"]
            == participant_binding_key_commitment_sha256
        )
        assert ticket["participantBindingSha256"] == participant_binding_sha256
        if ticket["cancelled_at"] is not None:
            raise StudyOperationsError("study_recruitment_ticket_cancelled", 409)
        return deepcopy(ticket)

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
        if self.fail_finalize_once:
            self.fail_finalize_once = False
            raise StudyOperationsError(
                "study_recruitment_finalization_failed", 503
            )
        if self.cancel_on_finalize:
            self.tickets[ticket_id]["cancelled_at"] = int(self.clock())
        ticket = self.assert_recruitment_ticket(
            proposal_id,
            ticket_id,
            ticket_sha256,
            participant_binding_sha256,
            participant_binding_key_id,
            participant_binding_key_commitment_sha256,
        )
        stored = self.tickets[ticket_id]
        assert stored["recruitmentTicketIssuedAt"] == consumed_at
        if stored["finalized_at"] is not None:
            assert stored["enrollment_sha256"] == enrollment_sha256
            assert stored["finalized_at"] == consumed_at
            return deepcopy(stored)
        stored["finalized_at"] = consumed_at
        stored["enrollment_sha256"] = enrollment_sha256
        return deepcopy(stored)

    def cancel_recruitment(self, _proposal_id, ticket_id):
        if self.fail_cancel:
            return
        ticket = self.tickets.get(ticket_id)
        if ticket is not None and ticket["finalized_at"] is None:
            ticket["cancelled_at"] = int(self.clock())

    def cancel_recruitment_reservation(
        self, _proposal_id, reservation_key_sha256
    ):
        if self.fail_cancel:
            return False
        for ticket in self.tickets.values():
            if (
                ticket["recruitmentReservationKeySha256"]
                == reservation_key_sha256
                and ticket["finalized_at"] is None
            ):
                ticket["cancelled_at"] = int(self.clock())
        return True

    def load_verified_recruitment_ticket(
        self,
        proposal_id,
        _permit_id,
        ticket_id,
        ticket_sha256,
        participant_binding_sha256,
        participant_binding_key_id,
        participant_binding_key_commitment_sha256,
        enrollment_sha256,
        consumed_at,
    ):
        ticket = self.tickets[ticket_id]
        assert ticket["proposalId"] == proposal_id
        assert ticket["recruitmentTicketSha256"] == ticket_sha256
        assert ticket["participantBindingKeyId"] == participant_binding_key_id
        assert (
            ticket["participantBindingKeyCommitmentSha256"]
            == participant_binding_key_commitment_sha256
        )
        assert ticket["participantBindingSha256"] == participant_binding_sha256
        assert ticket["enrollment_sha256"] == enrollment_sha256
        assert ticket["recruitmentTicketIssuedAt"] == consumed_at
        assert ticket["finalized_at"] == consumed_at
        assert ticket["cancelled_at"] is None
        return deepcopy(ticket)

    def enrollment_requires_renewal(self, _enrollment):
        return self.renewal_required

    def participant_tasks(self, enrollment, participant_id, completion_source):
        self.task_calls.append(
            (participant_id, enrollment["offeringId"], completion_source)
        )
        return {
            "schema": "brainstem.participant-study-tasks/v1",
            "offeringId": enrollment["offeringId"],
            "tasks": [],
        }


def _sign(account, message):
    return Account.sign_message(
        encode_defunct(text=message), account.key
    ).signature.hex()


def _answer(service, account, offering_id, answers):
    release = DEFAULT_STUDY_REGISTRY.release(offering_id)
    challenge = service.challenge(
        "session",
        ORIGIN,
        offering_id,
        "answer",
        {
            "releaseSha256": release["releaseSha256"],
            "surveyVersion": release["survey"]["version"],
            "answers": answers,
        },
    )
    return service.apply(
        "session",
        ORIGIN,
        offering_id,
        challenge["challengeId"],
        _sign(account, challenge["message"]),
    )


def _action(service, account, offering_id, action):
    status = service.status("session", ORIGIN, offering_id)
    if action == "withdraw":
        release_sha256 = status["enrollment"]["releaseSha256"]
    else:
        release_sha256 = status["offering"]["releaseSha256"]
    challenge = service.challenge(
        "session",
        ORIGIN,
        offering_id,
        action,
        release_sha256=release_sha256,
    )
    return service.apply(
        "session",
        ORIGIN,
        offering_id,
        challenge["challengeId"],
        _sign(account, challenge["message"]),
    )


def _install_recurring_private(dao, offering_id):
    private = dao.states["participant-one"]["offerings"][offering_id]
    private.update(
        {
            "recurringChallenge": {"nonce": "private-nonce"},
            "recurringEvidence": [{"signature": "private-signature"}],
            "recurringAuthorization": {
                "state": "active",
                "revision": 7,
                "lease": {"leaseTokenSha256": "a" * 64},
            },
            "recurringOutbox": [
                {
                    "notificationId": "n" * 64,
                    "messageKey": "study_result_ready",
                }
            ],
        }
    )
    return private


def _assert_recurring_scrubbed(private, terminal_state):
    assert not {
        "recurringChallenge",
        "recurringEvidence",
        "recurringAuthorization",
        "recurringOutbox",
    }.intersection(private)
    assert private["recurringTombstone"] == {
        "schema": "brainstem.study-recurring-tombstone/v1",
        "state": terminal_state,
        "revision": 7,
    }


def test_generated_generic_study_proof():
    """Marine invokes this as the generated-only backend proof checkpoint."""
    dao = Dao()
    one = GenericStudyService(Auth("participant-one", ACCOUNT_ONE), dao, clock=lambda: NOW)
    two = GenericStudyService(Auth("participant-two", ACCOUNT_TWO), dao, clock=lambda: NOW)

    first = _answer(one, ACCOUNT_ONE, COMMUNITY_QUESTIONNAIRE_ID, COMMUNITY_ANSWER)
    assert first["response"]["answers"] == COMMUNITY_ANSWER
    assert first["enrollment"] is None
    assert two.inbox("session", ORIGIN)["offerings"][0]["response"] is None

    revised = _answer(
        one,
        ACCOUNT_ONE,
        COMMUNITY_QUESTIONNAIRE_ID,
        {"health_priority": "heart_health", "follow_up_interest": "yes"},
    )
    assert revised["response"]["revision"] == 2
    assert revised["history"][0]["answers"] == COMMUNITY_ANSWER

    deleted = _action(one, ACCOUNT_ONE, COMMUNITY_QUESTIONNAIRE_ID, "delete")
    assert deleted["response"]["state"] == "deleted"
    assert deleted["response"]["answers"] is None
    assert all(item["answers"] is None for item in deleted["history"])
    serialized = repr(dao.states["participant-one"])
    assert "heart_health" not in serialized
    assert "follow_up_interest" not in serialized
    assert not any(
        receipt.get("offeringId") == COMMUNITY_QUESTIONNAIRE_ID
        for receipt in dao.states["participant-one"]["genericActionHistory"]
    )


def test_diagnosis_questionnaire_is_visible_and_writable_only_to_current_members():
    dao = Dao()
    hidden = GenericStudyService(
        Auth("participant-one", ACCOUNT_ONE), dao, clock=lambda: NOW
    )
    assert APDET_DIAGNOSIS_QUESTIONNAIRE_ID not in {
        item["offering"]["offeringId"]
        for item in hidden.inbox("session", ORIGIN)["offerings"]
    }
    assert APDET_DIAGNOSIS_QUESTIONNAIRE_ID not in {
        item["offeringId"] for item in hidden.catalogue()["offerings"]
    }
    with pytest.raises(GenericStudyServiceError, match="offering_unavailable"):
        hidden.status("session", ORIGIN, APDET_DIAGNOSIS_QUESTIONNAIRE_ID)

    access = {"allowed": True}
    member = GenericStudyService(
        Auth("participant-one", ACCOUNT_ONE),
        dao,
        clock=lambda: NOW,
        offering_access=lambda offering_id, user: (
            access["allowed"]
            and offering_id == APDET_DIAGNOSIS_QUESTIONNAIRE_ID
            and user["_id"] == "participant-one"
        ),
        available_offerings={APDET_DIAGNOSIS_QUESTIONNAIRE_ID},
    )
    assert APDET_DIAGNOSIS_QUESTIONNAIRE_ID in {
        item["offering"]["offeringId"]
        for item in member.inbox("session", ORIGIN)["offerings"]
    }
    release = DEFAULT_STUDY_REGISTRY.release(
        APDET_DIAGNOSIS_QUESTIONNAIRE_ID
    )
    challenge = member.challenge(
        "session",
        ORIGIN,
        APDET_DIAGNOSIS_QUESTIONNAIRE_ID,
        "answer",
        {
            "releaseSha256": release["releaseSha256"],
            "surveyVersion": release["survey"]["version"],
            "answers": {"sleep_apnea_diagnosis": "yes"},
        },
    )
    access["allowed"] = False
    with pytest.raises(GenericStudyServiceError, match="offering_unavailable"):
        member.apply(
            "session",
            ORIGIN,
            APDET_DIAGNOSIS_QUESTIONNAIRE_ID,
            challenge["challengeId"],
            _sign(ACCOUNT_ONE, challenge["message"]),
        )
    with pytest.raises(GenericStudyServiceError, match="offering_unavailable"):
        member.status("session", ORIGIN, COMMUNITY_QUESTIONNAIRE_ID)

    access["allowed"] = True
    saved = _answer(
        member,
        ACCOUNT_ONE,
        APDET_DIAGNOSIS_QUESTIONNAIRE_ID,
        {"sleep_apnea_diagnosis": "yes"},
    )
    assert saved["response"]["answers"] == {
        "sleep_apnea_diagnosis": "yes"
    }


def test_study_enrollment_is_distinct_and_correction_requires_renewal():
    dao = Dao()
    service = GenericStudyService(
        Auth("participant-one", ACCOUNT_ONE),
        dao,
        clock=lambda: NOW,
        operations=Operations(),
    )
    _answer(service, ACCOUNT_ONE, RECORDING_FEASIBILITY_ID, STUDY_ANSWER)

    enrolled = _action(service, ACCOUNT_ONE, RECORDING_FEASIBILITY_ID, "enroll")
    assert enrolled["enrollment"]["state"] == "active"
    assert enrolled["enrollment"]["endsAt"] - enrolled["enrollment"]["startsAt"] == 14 * 86400

    corrected = _answer(
        service,
        ACCOUNT_ONE,
        RECORDING_FEASIBILITY_ID,
        {**STUDY_ANSWER, "chronic_condition_status": "yes"},
    )
    assert corrected["enrollment"]["state"] == "renewal_required"


def test_study_enrollment_requires_recruiting_operations_and_binds_task_plan():
    dao = Dao()
    unavailable = GenericStudyService(
        Auth("participant-one", ACCOUNT_ONE), dao, clock=lambda: NOW
    )
    _answer(unavailable, ACCOUNT_ONE, RECORDING_FEASIBILITY_ID, STUDY_ANSWER)
    with pytest.raises(GenericStudyServiceError, match="study_operations_unavailable"):
        _action(unavailable, ACCOUNT_ONE, RECORDING_FEASIBILITY_ID, "enroll")

    operations = Operations()
    current = GenericStudyService(
        Auth("participant-one", ACCOUNT_ONE),
        dao,
        clock=lambda: NOW,
        operations=operations,
    )
    challenge = current.challenge(
        "session",
        ORIGIN,
        RECORDING_FEASIBILITY_ID,
        "enroll",
        release_sha256=DEFAULT_STUDY_REGISTRY.release(
            RECORDING_FEASIBILITY_ID
        )["releaseSha256"],
    )
    assert operations.tickets == {}
    assert "Task Plan Artifact SHA256:" in challenge["message"]
    assert "Operation State SHA256: {}".format("2" * 64) in challenge["message"]
    assert "Recruitment Ticket:" not in challenge["message"]
    enrolled = current.apply(
        "session",
        ORIGIN,
        RECORDING_FEASIBILITY_ID,
        challenge["challengeId"],
        _sign(ACCOUNT_ONE, challenge["message"]),
    )
    assert enrolled["enrollment"]["proposalId"] == "study_1234"
    assert enrolled["enrollment"]["permitId"] == "permit_" + "1" * 32
    assert enrolled["enrollment"]["taskPlan"] == DEFAULT_STUDY_REGISTRY.release(
        RECORDING_FEASIBILITY_ID
    )["taskPlan"]
    assert len(operations.tickets) == 1


def test_signed_reservation_is_preserved_when_participant_write_fails():
    dao = FailingDao()
    operations = Operations()
    service = GenericStudyService(
        Auth("participant-one", ACCOUNT_ONE),
        dao,
        clock=lambda: NOW,
        operations=operations,
    )
    _answer(service, ACCOUNT_ONE, RECORDING_FEASIBILITY_ID, STUDY_ANSWER)
    release = DEFAULT_STUDY_REGISTRY.release(RECORDING_FEASIBILITY_ID)
    challenge = service.challenge(
        "session",
        ORIGIN,
        RECORDING_FEASIBILITY_ID,
        "enroll",
        release_sha256=release["releaseSha256"],
    )
    dao.fail_next_mutation = True
    signature = _sign(ACCOUNT_ONE, challenge["message"])
    with pytest.raises(RuntimeError, match="participant store unavailable"):
        service.apply(
            "session",
            ORIGIN,
            RECORDING_FEASIBILITY_ID,
            challenge["challengeId"],
            signature,
        )
    first_id = "0" * 31 + "1"
    first = operations.tickets[first_id]
    assert first["finalized_at"] is None
    assert first["cancelled_at"] is None
    assert dao.states["participant-one"]["genericChallenge"]["consumedAt"] is None

    recovered = service.apply(
        "session",
        ORIGIN,
        RECORDING_FEASIBILITY_ID,
        challenge["challengeId"],
        signature,
    )
    assert recovered["enrollment"]["state"] == "active"
    assert dao.states["participant-one"]["offerings"][
        RECORDING_FEASIBILITY_ID
    ]["enrollment"]["recruitmentTicketId"] == first_id
    assert len(operations.tickets) == 1


def test_unsigned_enrollment_challenges_never_consume_recruitment_capacity():
    dao = Dao()
    operations = Operations()
    release = DEFAULT_STUDY_REGISTRY.release(RECORDING_FEASIBILITY_ID)
    for index in range(9):
        service = GenericStudyService(
            Auth("participant-{}".format(index), ACCOUNT_ONE),
            dao,
            clock=lambda: NOW,
            operations=operations,
        )
        _answer(service, ACCOUNT_ONE, RECORDING_FEASIBILITY_ID, STUDY_ANSWER)
        service.challenge(
            "session",
            ORIGIN,
            RECORDING_FEASIBILITY_ID,
            "enroll",
            release_sha256=release["releaseSha256"],
        )
    assert operations.tickets == {}


def test_verified_enrollment_replays_private_signature_ticket_and_current_wallet():
    dao = Dao()
    operations = Operations()
    service = GenericStudyService(
        Auth("participant-one", ACCOUNT_ONE),
        dao,
        clock=lambda: NOW,
        operations=operations,
    )
    _answer(service, ACCOUNT_ONE, RECORDING_FEASIBILITY_ID, STUDY_ANSWER)
    projected = _action(
        service, ACCOUNT_ONE, RECORDING_FEASIBILITY_ID, "enroll"
    )
    private = dao.states["participant-one"]["offerings"][
        RECORDING_FEASIBILITY_ID
    ]
    assert "signature" in private["enrollmentEvidence"]
    assert "message" in private["enrollmentEvidence"]["challenge"]
    assert BINDING_SECRET not in repr(dao.states["participant-one"])
    assert BINDING_SECRET not in repr(operations.tickets)
    assert "signature" not in repr(projected)
    assert "Recruitment Ticket:" not in repr(projected)
    user = {
        "_id": "participant-one",
        "public_address": ACCOUNT_ONE.address,
        "usage_flag": "ACCEPTED",
        "guidelines_acceptance_flag": "ACCEPTED",
    }
    assert service.load_verified_enrollment(
        "participant-one", RECORDING_FEASIBILITY_ID, user=user
    )["enrollmentSha256"] == private["enrollment"]["enrollmentSha256"]
    with pytest.raises(GenericStudyServiceError, match="evidence_invalid"):
        service.load_verified_enrollment(
            "participant-one", RECORDING_FEASIBILITY_ID
        )
    with pytest.raises(GenericStudyServiceError, match="evidence_invalid"):
        service.load_verified_enrollment(
            "participant-one",
            RECORDING_FEASIBILITY_ID,
            expected_address=ACCOUNT_TWO.address,
        )


def test_rehashed_enrollment_cannot_forge_authority():
    dao = Dao()
    service = GenericStudyService(
        Auth("participant-one", ACCOUNT_ONE),
        dao,
        clock=lambda: NOW,
        operations=Operations(),
    )
    _answer(service, ACCOUNT_ONE, RECORDING_FEASIBILITY_ID, STUDY_ANSWER)
    _action(service, ACCOUNT_ONE, RECORDING_FEASIBILITY_ID, "enroll")
    enrollment = dao.states["participant-one"]["offerings"][
        RECORDING_FEASIBILITY_ID
    ]["enrollment"]
    enrollment["proposalId"] = "study_deadbeef"
    enrollment["enrollmentSha256"] = _enrollment_sha256(enrollment)
    with pytest.raises(GenericStudyServiceError, match="evidence_invalid"):
        service.load_verified_enrollment(
            "participant-one",
            RECORDING_FEASIBILITY_ID,
            expected_address=ACCOUNT_ONE.address,
        )


def test_enrollment_consumed_time_is_actual_application_time():
    now = [NOW]
    operations = Operations(clock=lambda: now[0])
    dao = Dao()
    service = GenericStudyService(
        Auth("participant-one", ACCOUNT_ONE),
        dao,
        clock=lambda: now[0],
        operations=operations,
    )
    _answer(service, ACCOUNT_ONE, RECORDING_FEASIBILITY_ID, STUDY_ANSWER)
    release = DEFAULT_STUDY_REGISTRY.release(RECORDING_FEASIBILITY_ID)
    challenge = service.challenge(
        "session",
        ORIGIN,
        RECORDING_FEASIBILITY_ID,
        "enroll",
        release_sha256=release["releaseSha256"],
    )
    now[0] = NOW + 11
    service.apply(
        "session",
        ORIGIN,
        RECORDING_FEASIBILITY_ID,
        challenge["challengeId"],
        _sign(ACCOUNT_ONE, challenge["message"]),
    )
    private = dao.states["participant-one"]["offerings"][
        RECORDING_FEASIBILITY_ID
    ]
    assert private["enrollment"]["enrolledAt"] == NOW + 11
    assert private["enrollmentEvidence"]["challenge"]["consumedAt"] == NOW + 11
    assert operations.tickets[
        private["enrollment"]["recruitmentTicketId"]
    ]["finalized_at"] == NOW + 11


def test_enrollment_expiring_between_lookup_and_reservation_creates_no_ticket():
    now = [NOW]
    operations = Operations(clock=lambda: now[0])
    dao = Dao()
    service = GenericStudyService(
        Auth("participant-one", ACCOUNT_ONE),
        dao,
        clock=lambda: now[0],
        operations=operations,
    )
    _answer(service, ACCOUNT_ONE, RECORDING_FEASIBILITY_ID, STUDY_ANSWER)
    release = DEFAULT_STUDY_REGISTRY.release(RECORDING_FEASIBILITY_ID)
    challenge = service.challenge(
        "session",
        ORIGIN,
        RECORDING_FEASIBILITY_ID,
        "enroll",
        release_sha256=release["releaseSha256"],
    )
    ticks = iter((NOW + 299, NOW + 299, NOW + 300))
    service.clock = lambda: next(ticks)

    with pytest.raises(GenericStudyServiceError, match="challenge_unavailable"):
        service.apply(
            "session",
            ORIGIN,
            RECORDING_FEASIBILITY_ID,
            challenge["challengeId"],
            _sign(ACCOUNT_ONE, challenge["message"]),
        )
    assert operations.tickets == {}
    assert dao.states["participant-one"]["genericChallenge"][
        "consumedAt"
    ] is None


@pytest.mark.parametrize("ticket_ttl", (60, 300, 600))
def test_signed_recruitment_contract_binds_configured_ticket_ttl(ticket_ttl):
    dao = Dao()
    operations = Operations(ticket_ttl=ticket_ttl)
    service = GenericStudyService(
        Auth("participant-one", ACCOUNT_ONE),
        dao,
        clock=lambda: NOW,
        operations=operations,
    )
    _answer(service, ACCOUNT_ONE, RECORDING_FEASIBILITY_ID, STUDY_ANSWER)
    release = DEFAULT_STUDY_REGISTRY.release(RECORDING_FEASIBILITY_ID)
    challenge = service.challenge(
        "session",
        ORIGIN,
        RECORDING_FEASIBILITY_ID,
        "enroll",
        release_sha256=release["releaseSha256"],
    )
    assert "Recruitment Ticket TTL Seconds: {}".format(ticket_ttl) in challenge[
        "message"
    ]

    service.apply(
        "session",
        ORIGIN,
        RECORDING_FEASIBILITY_ID,
        challenge["challengeId"],
        _sign(ACCOUNT_ONE, challenge["message"]),
    )
    enrolled = dao.states["participant-one"]["offerings"][
        RECORDING_FEASIBILITY_ID
    ]["enrollment"]
    assert (
        enrolled["recruitmentTicketExpiresAt"]
        - enrolled["recruitmentTicketIssuedAt"]
        == ticket_ttl
    )


def test_same_key_id_secret_drift_fails_before_a_second_ticket():
    dao = Dao()
    operations = Operations()
    first = GenericStudyService(
        Auth("participant-one", ACCOUNT_ONE),
        dao,
        clock=lambda: NOW,
        operations=operations,
    )
    _answer(first, ACCOUNT_ONE, RECORDING_FEASIBILITY_ID, STUDY_ANSWER)
    _action(first, ACCOUNT_ONE, RECORDING_FEASIBILITY_ID, "enroll")
    assert len(operations.tickets) == 1

    drifted = GenericStudyService(
        Auth("participant-two", ACCOUNT_TWO),
        dao,
        clock=lambda: NOW,
        operations=operations,
        participant_binding_secret="2" * 64,
        participant_binding_key_id=BINDING_KEY_ID,
    )
    _answer(drifted, ACCOUNT_TWO, RECORDING_FEASIBILITY_ID, STUDY_ANSWER)
    release = DEFAULT_STUDY_REGISTRY.release(RECORDING_FEASIBILITY_ID)
    with pytest.raises(
        GenericStudyServiceError, match="study_recruitment_authority_changed"
    ):
        drifted.challenge(
            "session",
            ORIGIN,
            RECORDING_FEASIBILITY_ID,
            "enroll",
            release_sha256=release["releaseSha256"],
        )
    assert len(operations.tickets) == 1


def test_half_commit_retries_exact_finalization_without_duplicate_enrollment():
    dao = Dao()
    operations = Operations()
    operations.fail_finalize_once = True
    service = GenericStudyService(
        Auth("participant-one", ACCOUNT_ONE),
        dao,
        clock=lambda: NOW,
        operations=operations,
    )
    _answer(service, ACCOUNT_ONE, RECORDING_FEASIBILITY_ID, STUDY_ANSWER)
    release = DEFAULT_STUDY_REGISTRY.release(RECORDING_FEASIBILITY_ID)
    challenge = service.challenge(
        "session",
        ORIGIN,
        RECORDING_FEASIBILITY_ID,
        "enroll",
        release_sha256=release["releaseSha256"],
    )
    signature = _sign(ACCOUNT_ONE, challenge["message"])
    with pytest.raises(
        GenericStudyServiceError, match="study_recruitment_finalization_failed"
    ):
        service.apply(
            "session",
            ORIGIN,
            RECORDING_FEASIBILITY_ID,
            challenge["challengeId"],
            signature,
        )
    half = dao.states["participant-one"]
    first_sha256 = half["offerings"][RECORDING_FEASIBILITY_ID]["enrollment"][
        "enrollmentSha256"
    ]
    assert half["genericChallenge"]["consumedAt"] == NOW
    projected = service.status(
        "session", ORIGIN, RECORDING_FEASIBILITY_ID
    )
    assert projected["enrollment"]["state"] == "pending_finalization"
    recovered = service.apply(
        "session",
        ORIGIN,
        RECORDING_FEASIBILITY_ID,
        challenge["challengeId"],
        signature,
    )
    assert recovered["enrollment"]["state"] == "active"
    assert "genericChallenge" not in dao.states["participant-one"]
    assert (
        dao.states["participant-one"]["offerings"][RECORDING_FEASIBILITY_ID][
            "enrollment"
        ]["enrollmentSha256"]
        == first_sha256
    )


def test_finalized_ticket_recovers_after_challenge_clear_crash_and_expiry():
    now = [NOW]
    dao = ClearFailingDao()
    operations = Operations(clock=lambda: now[0])
    service = GenericStudyService(
        Auth("participant-one", ACCOUNT_ONE),
        dao,
        clock=lambda: now[0],
        operations=operations,
    )
    _answer(service, ACCOUNT_ONE, RECORDING_FEASIBILITY_ID, STUDY_ANSWER)
    release = DEFAULT_STUDY_REGISTRY.release(RECORDING_FEASIBILITY_ID)
    challenge = service.challenge(
        "session",
        ORIGIN,
        RECORDING_FEASIBILITY_ID,
        "enroll",
        release_sha256=release["releaseSha256"],
    )
    signature = _sign(ACCOUNT_ONE, challenge["message"])
    with pytest.raises(
        RuntimeError, match="participant challenge clear unavailable"
    ):
        service.apply(
            "session",
            ORIGIN,
            RECORDING_FEASIBILITY_ID,
            challenge["challengeId"],
            signature,
        )
    ticket = next(iter(operations.tickets.values()))
    assert ticket["finalized_at"] == NOW
    assert dao.states["participant-one"]["genericChallenge"][
        "consumedAt"
    ] == NOW

    now[0] = NOW + 301
    restarted = GenericStudyService(
        Auth("participant-one", ACCOUNT_ONE),
        dao,
        clock=lambda: now[0],
        operations=operations,
    )
    recovered = restarted.status(
        "session", ORIGIN, RECORDING_FEASIBILITY_ID
    )
    assert recovered["enrollment"]["state"] == "active"
    assert "genericChallenge" not in dao.states["participant-one"]
    assert next(iter(operations.tickets.values()))["finalized_at"] == NOW


def test_concurrent_same_challenge_preserves_the_winners_ticket():
    dao = LockedDao()

    class ConcurrentOperations(Operations):
        def __init__(self):
            super().__init__()
            self.reserve_lock = threading.Lock()
            self.finalize_started = threading.Event()
            self.allow_finalize = threading.Event()

        def reserve_recruitment(self, *args, **kwargs):
            with self.reserve_lock:
                return super().reserve_recruitment(*args, **kwargs)

        def finalize_recruitment(self, *args, **kwargs):
            self.finalize_started.set()
            assert self.allow_finalize.wait(5)
            return super().finalize_recruitment(*args, **kwargs)

    operations = ConcurrentOperations()
    service = GenericStudyService(
        Auth("participant-one", ACCOUNT_ONE),
        dao,
        clock=lambda: NOW,
        operations=operations,
    )
    _answer(service, ACCOUNT_ONE, RECORDING_FEASIBILITY_ID, STUDY_ANSWER)
    release = DEFAULT_STUDY_REGISTRY.release(RECORDING_FEASIBILITY_ID)
    challenge = service.challenge(
        "session",
        ORIGIN,
        RECORDING_FEASIBILITY_ID,
        "enroll",
        release_sha256=release["releaseSha256"],
    )
    signature = _sign(ACCOUNT_ONE, challenge["message"])
    start = threading.Barrier(3)
    outcomes = []

    def apply():
        start.wait()
        try:
            outcomes.append(
                service.apply(
                    "session",
                    ORIGIN,
                    RECORDING_FEASIBILITY_ID,
                    challenge["challengeId"],
                    signature,
                )
            )
        except Exception as error:
            outcomes.append(error)

    workers = [threading.Thread(target=apply) for _index in range(2)]
    for worker in workers:
        worker.start()
    start.wait()
    assert operations.finalize_started.wait(5)
    operations.allow_finalize.set()
    for worker in workers:
        worker.join(5)
        assert not worker.is_alive()

    successes = [item for item in outcomes if isinstance(item, dict)]
    errors = [item for item in outcomes if isinstance(item, Exception)]
    assert len(successes) == 1
    assert successes[0]["enrollment"]["state"] == "active"
    assert len(errors) == 1
    assert isinstance(errors[0], GenericStudyServiceError)
    assert errors[0].code == "challenge_unavailable"
    assert len(operations.tickets) == 1
    ticket = next(iter(operations.tickets.values()))
    assert ticket["finalized_at"] == NOW
    assert ticket["cancelled_at"] is None


def test_orphaned_reservation_retry_reuses_the_exact_ticket():
    now = [NOW]
    dao = FailingDao()
    operations = Operations(clock=lambda: now[0])
    operations.fail_cancel = True
    service = GenericStudyService(
        Auth("participant-one", ACCOUNT_ONE),
        dao,
        clock=lambda: now[0],
        operations=operations,
    )
    _answer(service, ACCOUNT_ONE, RECORDING_FEASIBILITY_ID, STUDY_ANSWER)
    release = DEFAULT_STUDY_REGISTRY.release(RECORDING_FEASIBILITY_ID)
    challenge = service.challenge(
        "session",
        ORIGIN,
        RECORDING_FEASIBILITY_ID,
        "enroll",
        release_sha256=release["releaseSha256"],
    )
    signature = _sign(ACCOUNT_ONE, challenge["message"])
    dao.fail_next_mutation = True
    with pytest.raises(RuntimeError, match="participant store unavailable"):
        service.apply(
            "session",
            ORIGIN,
            RECORDING_FEASIBILITY_ID,
            challenge["challengeId"],
            signature,
        )
    orphan_id = next(iter(operations.tickets))
    assert operations.tickets[orphan_id]["cancelled_at"] is None

    operations.fail_cancel = False
    now[0] = NOW + 10
    recovered = service.apply(
        "session",
        ORIGIN,
        RECORDING_FEASIBILITY_ID,
        challenge["challengeId"],
        signature,
    )
    assert recovered["enrollment"]["state"] == "active"
    enrollment = dao.states["participant-one"]["offerings"][
        RECORDING_FEASIBILITY_ID
    ]["enrollment"]
    assert enrollment["recruitmentTicketId"] == orphan_id
    assert enrollment["enrolledAt"] == NOW
    assert operations.tickets[orphan_id]["finalized_at"] == NOW
    assert len(operations.tickets) == 1


def test_expired_orphan_is_reconciled_after_cancellation_failure():
    now = [NOW]
    dao = FailingDao()
    operations = Operations(clock=lambda: now[0])
    operations.fail_cancel = True
    service = GenericStudyService(
        Auth("participant-one", ACCOUNT_ONE),
        dao,
        clock=lambda: now[0],
        operations=operations,
    )
    _answer(service, ACCOUNT_ONE, RECORDING_FEASIBILITY_ID, STUDY_ANSWER)
    release = DEFAULT_STUDY_REGISTRY.release(RECORDING_FEASIBILITY_ID)
    challenge = service.challenge(
        "session",
        ORIGIN,
        RECORDING_FEASIBILITY_ID,
        "enroll",
        release_sha256=release["releaseSha256"],
    )
    dao.fail_next_mutation = True
    with pytest.raises(RuntimeError, match="participant store unavailable"):
        service.apply(
            "session",
            ORIGIN,
            RECORDING_FEASIBILITY_ID,
            challenge["challengeId"],
            _sign(ACCOUNT_ONE, challenge["message"]),
        )
    orphan = next(iter(operations.tickets.values()))
    assert orphan["cancelled_at"] is None

    now[0] = NOW + 301
    with pytest.raises(
        GenericStudyServiceError,
        match="study_recruitment_reconciliation_pending",
    ):
        service.status("session", ORIGIN, RECORDING_FEASIBILITY_ID)
    assert orphan["cancelled_at"] is None
    assert "genericChallenge" in dao.states["participant-one"]

    operations.fail_cancel = False
    service.status("session", ORIGIN, RECORDING_FEASIBILITY_ID)
    assert orphan["cancelled_at"] == NOW + 301
    assert "genericChallenge" not in dao.states["participant-one"]
    assert "participant-one" not in repr(orphan)


def test_participant_binding_is_keyed_and_scoped_to_the_exact_release():
    old_release = DEFAULT_STUDY_REGISTRY.release(RECORDING_FEASIBILITY_ID)
    new_release = amended_registry().release(RECORDING_FEASIBILITY_ID)
    old_binding = _participant_binding(
        BINDING_SECRET,
        BINDING_KEY_ID,
        "participant-one",
        RECORDING_FEASIBILITY_ID,
        old_release["releaseSha256"],
    )
    assert old_binding != _participant_binding(
        BINDING_SECRET,
        BINDING_KEY_ID,
        "participant-one",
        RECORDING_FEASIBILITY_ID,
        new_release["releaseSha256"],
    )
    assert old_binding != hashlib.sha256(
        b"brainstem.study.participant/v1\0participant-one"
    ).hexdigest()
    assert "participant-one" not in old_binding
    old_commitment = _participant_binding_secret_commitment(
        BINDING_SECRET,
        BINDING_KEY_ID,
        RECORDING_FEASIBILITY_ID,
        old_release["releaseSha256"],
    )
    assert old_commitment != _participant_binding_secret_commitment(
        BINDING_SECRET,
        BINDING_KEY_ID,
        RECORDING_FEASIBILITY_ID,
        new_release["releaseSha256"],
    )
    community = DEFAULT_STUDY_REGISTRY.release(COMMUNITY_QUESTIONNAIRE_ID)
    assert old_commitment != _participant_binding_secret_commitment(
        BINDING_SECRET,
        BINDING_KEY_ID,
        COMMUNITY_QUESTIONNAIRE_ID,
        community["releaseSha256"],
    )


@pytest.mark.parametrize(
    "secret",
    (
        "1" * 63,
        "1" * 65,
        "G" * 64,
        "A" * 64,
        "test-only-participant-binding-secret-32-bytes",
    ),
)
def test_participant_binding_secret_requires_canonical_256_bit_hex(secret):
    release = DEFAULT_STUDY_REGISTRY.release(RECORDING_FEASIBILITY_ID)
    with pytest.raises(
        GenericStudyServiceError,
        match="participant_binding_configuration_invalid",
    ):
        _participant_binding_secret_commitment(
            secret,
            BINDING_KEY_ID,
            RECORDING_FEASIBILITY_ID,
            release["releaseSha256"],
        )


def test_cancelled_half_commit_is_scrubbed_and_can_recruit_again():
    dao = Dao()
    operations = Operations()
    operations.cancel_on_finalize = True
    service = GenericStudyService(
        Auth("participant-one", ACCOUNT_ONE),
        dao,
        clock=lambda: NOW,
        operations=operations,
    )
    _answer(service, ACCOUNT_ONE, RECORDING_FEASIBILITY_ID, STUDY_ANSWER)
    with pytest.raises(
        GenericStudyServiceError, match="study_recruitment_ticket_cancelled"
    ):
        _action(service, ACCOUNT_ONE, RECORDING_FEASIBILITY_ID, "enroll")
    private = dao.states["participant-one"]["offerings"][
        RECORDING_FEASIBILITY_ID
    ]
    assert private["enrollment"]["state"] == "failed"
    assert "enrollmentEvidence" not in private
    assert "genericChallenge" not in dao.states["participant-one"]
    operations.cancel_on_finalize = False
    retried = _action(
        service, ACCOUNT_ONE, RECORDING_FEASIBILITY_ID, "enroll"
    )
    assert retried["enrollment"]["state"] == "active"


def test_superseded_operations_conservatively_persist_renewal_required():
    dao = Dao()
    operations = Operations()
    current = GenericStudyService(
        Auth("participant-one", ACCOUNT_ONE),
        dao,
        clock=lambda: NOW,
        operations=operations,
    )
    _answer(current, ACCOUNT_ONE, RECORDING_FEASIBILITY_ID, STUDY_ANSWER)
    _action(current, ACCOUNT_ONE, RECORDING_FEASIBILITY_ID, "enroll")
    recurring = _install_recurring_private(dao, RECORDING_FEASIBILITY_ID)
    operations.renewal_required = True

    status = current.status("session", ORIGIN, RECORDING_FEASIBILITY_ID)
    stored = dao.states["participant-one"]["offerings"][
        RECORDING_FEASIBILITY_ID
    ]["enrollment"]
    assert status["enrollment"]["state"] == "renewal_required"
    assert stored["state"] == "renewal_required"
    assert stored["renewalRequiredAt"] == NOW
    assert stored["enrollmentSha256"] == _enrollment_sha256(stored)
    assert recurring is not dao.states["participant-one"]["offerings"][
        RECORDING_FEASIBILITY_ID
    ]
    private = dao.states["participant-one"]["offerings"][
        RECORDING_FEASIBILITY_ID
    ]
    assert private["recurringAuthorization"]["lease"] is None
    assert "recurringChallenge" not in private
    assert "recurringOutbox" not in private
    assert private["recurringEvidence"] == [{"signature": "private-signature"}]


def test_delete_scrubs_all_ticket_join_keys_from_participant_state():
    dao = Dao()
    operations = Operations()
    service = GenericStudyService(
        Auth("participant-one", ACCOUNT_ONE),
        dao,
        clock=lambda: NOW,
        operations=operations,
    )
    _answer(service, ACCOUNT_ONE, RECORDING_FEASIBILITY_ID, STUDY_ANSWER)
    _action(service, ACCOUNT_ONE, RECORDING_FEASIBILITY_ID, "enroll")
    _install_recurring_private(dao, RECORDING_FEASIBILITY_ID)
    previous_hash = dao.states["participant-one"]["offerings"][
        RECORDING_FEASIBILITY_ID
    ]["enrollment"]["enrollmentSha256"]
    ticket = deepcopy(next(iter(operations.tickets.values())))

    deleted = _action(service, ACCOUNT_ONE, RECORDING_FEASIBILITY_ID, "delete")
    persisted = dao.states["participant-one"]["offerings"][
        RECORDING_FEASIBILITY_ID
    ]["enrollment"]

    assert deleted["enrollment"]["state"] == "withdrawn"
    assert persisted["enrollmentSha256"] != previous_hash
    assert persisted["enrollmentSha256"] == _enrollment_sha256(persisted)
    private = dao.states["participant-one"]["offerings"][
        RECORDING_FEASIBILITY_ID
    ]
    _assert_recurring_scrubbed(private, "deleted")
    assert "enrollmentEvidence" not in private
    assert "message" not in repr(private)
    assert "signature" not in repr(private)
    unkeyed_global_binding = hashlib.sha256(
        b"brainstem.study.participant/v1\0participant-one"
    ).hexdigest()
    assert unkeyed_global_binding not in repr(operations.tickets)
    assert "participant-one" not in repr(operations.tickets)
    assert BINDING_KEY_ID in repr(operations.tickets)
    assert set(private["response"]) == {
        "schema",
        "offeringId",
        "revision",
        "state",
        "deletedOn",
    }
    assert not any(
        receipt.get("offeringId") == RECORDING_FEASIBILITY_ID
        for receipt in dao.states["participant-one"]["genericActionHistory"]
    )

    def scalar_values(value):
        if isinstance(value, dict):
            return set().union(
                *(scalar_values(item) for item in value.values())
            ) if value else set()
        if isinstance(value, list):
            return set().union(
                *(scalar_values(item) for item in value)
            ) if value else set()
        if type(value) in {str, int}:
            return {value}
        return set()

    ticket_join_values = {
        ticket[key]
        for key in (
            "proposalId",
            "permitId",
            "operationStateSha256",
            "participantBindingKeyId",
            "participantBindingKeyCommitmentSha256",
            "participantBindingSha256",
            "recruitmentReservationKeySha256",
            "recruitmentTicketId",
            "recruitmentTicketSha256",
            "recruitmentTicketIssuedAt",
            "recruitmentTicketExpiresAt",
            "startsAt",
            "endsAt",
            "finalized_at",
            "enrollment_sha256",
        )
    }
    ticket_join_values.add(
        DEFAULT_STUDY_REGISTRY.release(RECORDING_FEASIBILITY_ID)[
            "releaseSha256"
        ]
    )
    assert scalar_values(dao.states["participant-one"]).isdisjoint(
        ticket_join_values
    )


def test_questionnaire_cannot_enroll_and_challenge_replay_fails():
    dao = Dao()
    service = GenericStudyService(Auth("participant-one", ACCOUNT_ONE), dao, clock=lambda: NOW)
    _answer(service, ACCOUNT_ONE, COMMUNITY_QUESTIONNAIRE_ID, COMMUNITY_ANSWER)
    with pytest.raises(
        GenericStudyServiceError, match="questionnaire_enrollment_forbidden"
    ):
        service.challenge(
            "session", ORIGIN, COMMUNITY_QUESTIONNAIRE_ID, "enroll"
        )

    release = DEFAULT_STUDY_REGISTRY.release(COMMUNITY_QUESTIONNAIRE_ID)
    challenge = service.challenge(
        "session",
        ORIGIN,
        COMMUNITY_QUESTIONNAIRE_ID,
        "answer",
        {
            "releaseSha256": release["releaseSha256"],
            "surveyVersion": "1.0.0",
            "answers": {"health_priority": "activity"},
        },
    )
    signature = _sign(ACCOUNT_ONE, challenge["message"])
    service.apply(
        "session",
        ORIGIN,
        COMMUNITY_QUESTIONNAIRE_ID,
        challenge["challengeId"],
        signature,
    )
    with pytest.raises(GenericStudyServiceError, match="challenge_unavailable"):
        service.apply(
            "session",
            ORIGIN,
            COMMUNITY_QUESTIONNAIRE_ID,
            challenge["challengeId"],
            signature,
        )


def test_signed_message_binds_data_union_release_and_all_artifact_refs():
    service = GenericStudyService(Auth("participant-one", ACCOUNT_ONE), Dao(), clock=lambda: NOW)
    release = DEFAULT_STUDY_REGISTRY.release(COMMUNITY_QUESTIONNAIRE_ID)
    challenge = service.challenge(
        "session",
        ORIGIN,
        COMMUNITY_QUESTIONNAIRE_ID,
        "answer",
        {
            "releaseSha256": release["releaseSha256"],
            "surveyVersion": "1.0.0",
            "answers": COMMUNITY_ANSWER,
        },
    )
    assert "Data Union: brainstem" in challenge["message"]
    assert "Purpose Artifact SHA256: {}".format(release["purpose"]["sha256"]) in challenge["message"]
    assert "Survey Artifact SHA256: {}".format(release["survey"]["sha256"]) in challenge["message"]


def test_pending_answer_is_memory_only_and_expired_challenge_is_removed():
    dao = Dao()
    now = [NOW]
    service = GenericStudyService(
        Auth("participant-one", ACCOUNT_ONE), dao, clock=lambda: now[0]
    )
    release = DEFAULT_STUDY_REGISTRY.release(COMMUNITY_QUESTIONNAIRE_ID)
    challenge = service.challenge(
        "session",
        ORIGIN,
        COMMUNITY_QUESTIONNAIRE_ID,
        "answer",
        {
            "releaseSha256": release["releaseSha256"],
            "surveyVersion": "1.0.0",
            "answers": COMMUNITY_ANSWER,
        },
    )
    persisted = repr(dao.states["participant-one"]["genericChallenge"])
    assert "health_priority" not in persisted
    assert "'sleep'" not in persisted
    assert "pendingResponse" not in persisted

    now[0] = NOW + 301
    with pytest.raises(GenericStudyServiceError, match="challenge_unavailable"):
        service.apply(
            "session",
            ORIGIN,
            COMMUNITY_QUESTIONNAIRE_ID,
            challenge["challengeId"],
            _sign(ACCOUNT_ONE, challenge["message"]),
        )
    assert "genericChallenge" not in dao.states["participant-one"]
    assert service.pending_answers.get(challenge["challengeId"], now[0]) is None


def test_duplicate_answer_is_noop_and_does_not_consume_action_history():
    dao = Dao()
    service = GenericStudyService(
        Auth("participant-one", ACCOUNT_ONE), dao, clock=lambda: NOW
    )
    first = _answer(
        service, ACCOUNT_ONE, COMMUNITY_QUESTIONNAIRE_ID, COMMUNITY_ANSWER
    )
    receipts = len(dao.states["participant-one"]["genericActionHistory"])
    duplicate = _answer(
        service, ACCOUNT_ONE, COMMUNITY_QUESTIONNAIRE_ID, COMMUNITY_ANSWER
    )

    assert duplicate["response"] == first["response"]
    assert len(dao.states["participant-one"]["genericActionHistory"]) == receipts


def test_rolling_action_history_never_blocks_delete():
    dao = Dao()
    service = GenericStudyService(
        Auth("participant-one", ACCOUNT_ONE), dao, clock=lambda: NOW
    )
    original = _answer(
        service, ACCOUNT_ONE, COMMUNITY_QUESTIONNAIRE_ID, COMMUNITY_ANSWER
    )
    _install_recurring_private(dao, COMMUNITY_QUESTIONNAIRE_ID)
    dao.states["participant-one"]["genericActionHistory"] = [
        {
            "schema": "brainstem.study-offering-action-receipt/v1",
            "offeringId": COMMUNITY_QUESTIONNAIRE_ID,
            "releaseSha256": DEFAULT_STUDY_REGISTRY.release(
                COMMUNITY_QUESTIONNAIRE_ID
            )["releaseSha256"],
            "action": "answer",
            "occurredAt": NOW,
        }
        for _index in range(MAX_ACTION_HISTORY)
    ] + [
        {
            "schema": "brainstem.study-offering-action-receipt/v1",
            "offeringId": RECORDING_FEASIBILITY_ID,
            "releaseSha256": "f" * 64,
            "action": "answer",
            "occurredAt": NOW - 1,
        }
    ]
    release = DEFAULT_STUDY_REGISTRY.release(COMMUNITY_QUESTIONNAIRE_ID)
    deleted = _action(service, ACCOUNT_ONE, COMMUNITY_QUESTIONNAIRE_ID, "delete")
    assert original["response"]["state"] == "active"
    assert deleted["response"]["state"] == "deleted"
    history = dao.states["participant-one"]["genericActionHistory"]
    assert len(history) == 1
    assert history[0]["offeringId"] == RECORDING_FEASIBILITY_ID
    _assert_recurring_scrubbed(
        dao.states["participant-one"]["offerings"][COMMUNITY_QUESTIONNAIRE_ID],
        "deleted",
    )


def test_rolling_action_history_never_blocks_withdrawal_after_amendment():
    dao = Dao()
    original = GenericStudyService(
        Auth("participant-one", ACCOUNT_ONE),
        dao,
        clock=lambda: NOW,
        operations=Operations(),
    )
    _answer(original, ACCOUNT_ONE, RECORDING_FEASIBILITY_ID, STUDY_ANSWER)
    _action(original, ACCOUNT_ONE, RECORDING_FEASIBILITY_ID, "enroll")
    _install_recurring_private(dao, RECORDING_FEASIBILITY_ID)
    dao.states["participant-one"]["genericActionHistory"] = [
        {
            "schema": "brainstem.study-offering-action-receipt/v1",
            "offeringId": RECORDING_FEASIBILITY_ID,
            "releaseSha256": DEFAULT_STUDY_REGISTRY.release(
                RECORDING_FEASIBILITY_ID
            )["releaseSha256"],
            "action": "answer",
            "occurredAt": NOW,
        }
        for _index in range(MAX_ACTION_HISTORY + 20)
    ]
    amended = GenericStudyService(
        Auth("participant-one", ACCOUNT_ONE),
        dao,
        registry=amended_registry(),
        clock=lambda: NOW,
        operations=Operations(amended_registry()),
    )
    withdrawn = _action(
        amended, ACCOUNT_ONE, RECORDING_FEASIBILITY_ID, "withdraw"
    )
    assert withdrawn["enrollment"]["state"] == "withdrawn"
    assert len(dao.states["participant-one"]["genericActionHistory"]) == MAX_ACTION_HISTORY
    assert (
        dao.states["participant-one"]["genericActionHistory"][-1][
            "releaseSha256"
        ]
        == DEFAULT_STUDY_REGISTRY.release(RECORDING_FEASIBILITY_ID)[
            "releaseSha256"
        ]
    )
    _assert_recurring_scrubbed(
        dao.states["participant-one"]["offerings"][RECORDING_FEASIBILITY_ID],
        "revoked",
    )


def test_withdrawal_from_renewal_required_binds_original_enrollment_release():
    dao = Dao()
    original = GenericStudyService(
        Auth("participant-one", ACCOUNT_ONE),
        dao,
        clock=lambda: NOW,
        operations=Operations(),
    )
    _answer(original, ACCOUNT_ONE, RECORDING_FEASIBILITY_ID, STUDY_ANSWER)
    _action(original, ACCOUNT_ONE, RECORDING_FEASIBILITY_ID, "enroll")
    old_release = DEFAULT_STUDY_REGISTRY.release(RECORDING_FEASIBILITY_ID)

    registry = amended_registry()
    amended = GenericStudyService(
        Auth("participant-one", ACCOUNT_ONE),
        dao,
        registry=registry,
        clock=lambda: NOW,
        operations=Operations(registry),
    )
    latest = registry.release(RECORDING_FEASIBILITY_ID)
    challenge = amended.challenge(
        "session",
        ORIGIN,
        RECORDING_FEASIBILITY_ID,
        "answer",
        {
            "releaseSha256": latest["releaseSha256"],
            "surveyVersion": latest["survey"]["version"],
            "answers": STUDY_ANSWER,
        },
    )
    corrected = amended.apply(
        "session",
        ORIGIN,
        RECORDING_FEASIBILITY_ID,
        challenge["challengeId"],
        _sign(ACCOUNT_ONE, challenge["message"]),
    )
    assert corrected["enrollment"]["state"] == "renewal_required"
    assert corrected["enrollment"]["releaseVersion"] == "1.0.0"

    withdrawal = amended.challenge(
        "session",
        ORIGIN,
        RECORDING_FEASIBILITY_ID,
        "withdraw",
        release_sha256=old_release["releaseSha256"],
    )
    assert "Release Version: 1.0.0" in withdrawal["message"]
    assert "Release SHA256: {}".format(old_release["releaseSha256"]) in withdrawal[
        "message"
    ]
    withdrawn = amended.apply(
        "session",
        ORIGIN,
        RECORDING_FEASIBILITY_ID,
        withdrawal["challengeId"],
        _sign(ACCOUNT_ONE, withdrawal["message"]),
    )
    assert withdrawn["enrollment"]["state"] == "withdrawn"
    assert (
        dao.states["participant-one"]["genericActionHistory"][-1][
            "releaseSha256"
        ]
        == old_release["releaseSha256"]
    )


def test_old_bound_response_remains_valid_but_cannot_enroll_until_amended():
    registry = amended_registry()
    old_response = create_response(
        registry,
        RECORDING_FEASIBILITY_ID,
        STUDY_ANSWER,
        submitted_at=NOW,
        release_version="1.0.0",
    )
    validate_response(registry, RECORDING_FEASIBILITY_ID, old_response)
    dao = Dao()
    dao.states["participant-one"] = {
        "document_type": "brainstem_study_participant_state",
        "user_id": "participant-one",
        "offerings": {
            RECORDING_FEASIBILITY_ID: {"response": deepcopy(old_response)}
        },
    }
    service = GenericStudyService(
        Auth("participant-one", ACCOUNT_ONE),
        dao,
        registry=registry,
        clock=lambda: NOW,
        operations=Operations(registry),
    )
    status = service.status("session", ORIGIN, RECORDING_FEASIBILITY_ID)
    assert status["offering"]["releaseVersion"] == "2.0.0"
    assert status["response"]["releaseVersion"] == "1.0.0"
    with pytest.raises(
        GenericStudyServiceError, match="current_release_response_required"
    ):
        service.challenge(
            "session", ORIGIN, RECORDING_FEASIBILITY_ID, "enroll"
        )

    latest = registry.release(RECORDING_FEASIBILITY_ID)
    challenge = service.challenge(
        "session",
        ORIGIN,
        RECORDING_FEASIBILITY_ID,
        "answer",
        {
            "releaseSha256": latest["releaseSha256"],
            "surveyVersion": latest["survey"]["version"],
            "answers": STUDY_ANSWER,
        },
    )
    amended = service.apply(
        "session",
        ORIGIN,
        RECORDING_FEASIBILITY_ID,
        challenge["challengeId"],
        _sign(ACCOUNT_ONE, challenge["message"]),
    )
    assert amended["response"]["releaseVersion"] == "2.0.0"
    assert amended["response"]["revision"] == 2
    assert amended["history"][0]["releaseVersion"] == "1.0.0"
    enrolled = _action(service, ACCOUNT_ONE, RECORDING_FEASIBILITY_ID, "enroll")
    assert enrolled["enrollment"]["state"] == "active"


def test_participant_tasks_use_only_authenticated_participant_enrollment():
    dao = Dao()
    operations = Operations()
    one = GenericStudyService(
        Auth("participant-one", ACCOUNT_ONE),
        dao,
        clock=lambda: NOW,
        operations=operations,
    )
    two = GenericStudyService(
        Auth("participant-two", ACCOUNT_TWO),
        dao,
        clock=lambda: NOW,
        operations=operations,
    )
    for service, account in ((one, ACCOUNT_ONE), (two, ACCOUNT_TWO)):
        _answer(service, account, RECORDING_FEASIBILITY_ID, STUDY_ANSWER)
        _action(service, account, RECORDING_FEASIBILITY_ID, "enroll")

    first = one.tasks("session", ORIGIN, RECORDING_FEASIBILITY_ID)
    second = two.tasks("session", ORIGIN, RECORDING_FEASIBILITY_ID)
    assert first == second
    assert [item[0] for item in operations.task_calls] == [
        "participant-one",
        "participant-two",
    ]
    assert "participant-one" not in repr(first)
    assert "participant-two" not in repr(second)
    with pytest.raises(GenericStudyServiceError, match="study_tasks_unavailable"):
        one.tasks("session", ORIGIN, COMMUNITY_QUESTIONNAIRE_ID)
