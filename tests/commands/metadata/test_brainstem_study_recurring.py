from copy import deepcopy
from configparser import ConfigParser
import json

import pytest
from eth_account import Account
from eth_account.messages import encode_defunct

from commands.dataunions.brainstem.study_recurring import (
    GeneratedStudyRecurringWorker,
    MAX_OUTBOX,
    StudyRecurringError,
    StudyRecurringService,
    block_recurring_for_renewal,
    scrub_recurring,
)
from commands.dataunions.brainstem.study_registry import (
    DEFAULT_STUDY_REGISTRY,
    RECORDING_FEASIBILITY_ID,
)


NOW = 1_800_000_000
ORIGIN = "https://desci.example"
ACCOUNT_ONE = Account.from_key("0x" + "61" * 32)
ACCOUNT_TWO = Account.from_key("0x" + "62" * 32)
PROPOSAL_ID = "study_abcd"
PERMIT_ID = "permit_" + "1" * 32
PERMIT_SHA256 = "2" * 64
STATE_SHA256 = "3" * 64
SETTINGS = {
    "cadenceDays": 7,
    "maximumRunsPer30Days": 4,
    "maximumChargeMinor": 0,
    "currency": "none",
    "notification": "in_app",
    "retentionDays": 14,
    "minimumNewRecordings": 2,
    "startsAt": NOW,
    "expiresAt": NOW + 30 * 86400,
    "entitlement": "no_charge",
}


def user(user_id, account):
    return {
        "_id": user_id,
        "public_address": account.address,
        "usage_flag": "ACCEPTED",
        "guidelines_acceptance_flag": "ACCEPTED",
        "is_access_blocked": False,
    }


class Auth:
    def __init__(self, users):
        self.users = users

    def authenticate(self, token, origin):
        if origin != ORIGIN or token not in self.users:
            raise RuntimeError("invalid participant session")
        return "session", {}, deepcopy(self.users[token])


class UsersDao:
    def __init__(self, users):
        self.users = users
        self.error = None

    def get_doc_by_id(self, user_id):
        if self.error:
            raise self.error
        return deepcopy(self.users[user_id])


class StudyDao:
    def __init__(self, states):
        self.states = states
        self.conflict_once = False
        self.mutations = 0

    def get_state(self, user_id):
        return deepcopy(self.states.get(user_id))

    def mutate_state(self, user_id, mutator):
        self.mutations += 1
        current = deepcopy(self.states[user_id])
        if self.conflict_once:
            self.conflict_once = False
            mutator(deepcopy(current))
            current = deepcopy(self.states[user_id])
        updated = mutator(current)
        self.states[user_id] = deepcopy(updated)
        return deepcopy(updated)


class Enrollments:
    def __init__(self):
        self.error = None

    def load_verified_enrollment(self, user_id, offering_id, *, state, user):
        if self.error:
            raise self.error
        if user.get("_id") != user_id:
            raise RuntimeError("identity changed")
        enrollment = state["offerings"][offering_id]["enrollment"]
        if enrollment.get("state") != "active":
            raise RuntimeError("enrollment inactive")
        return deepcopy(enrollment)


class Operations:
    def __init__(self, release):
        self.renewal_required = False
        self.allowed = True
        self.denied_capabilities = set()
        self.mutate_during_allowed = False
        self.error = None
        self.state = {
            "proposalId": PROPOSAL_ID,
            "permitId": PERMIT_ID,
            "permitSha256": PERMIT_SHA256,
            "offeringId": release["offeringId"],
            "releaseVersion": release["releaseVersion"],
            "releaseSha256": release["releaseSha256"],
            "taskPlan": deepcopy(release["taskPlan"]),
            "lifecycleState": "active",
            "disposition": "current",
            "stateSha256": STATE_SHA256,
        }

    def enrollment_requires_renewal(self, _enrollment):
        if self.error:
            raise self.error
        return self.renewal_required

    def load_verified_status(self, proposal_id, permit_id):
        if self.error:
            raise self.error
        assert proposal_id == PROPOSAL_ID
        assert permit_id == PERMIT_ID
        return {"state": deepcopy(self.state), "events": [{"verified": True}]}

    def operation_allowed(self, proposal_id, permit_id, capability):
        if self.error:
            raise self.error
        assert proposal_id == PROPOSAL_ID
        assert permit_id == PERMIT_ID
        assert capability in {"lease", "reminder"}
        if self.mutate_during_allowed:
            self.mutate_during_allowed = False
            self.state["stateSha256"] = "f" * 64
        return (
            self.allowed
            and capability not in self.denied_capabilities
            and self.state["lifecycleState"] == "active"
            and self.state["disposition"] == "current"
        )


def enrollment(release, user_id):
    return {
        "state": "active",
        "proposalId": PROPOSAL_ID,
        "permitId": PERMIT_ID,
        "releaseVersion": release["releaseVersion"],
        "releaseSha256": release["releaseSha256"],
        "taskPlan": deepcopy(release["taskPlan"]),
        "enrollmentSha256": ("a" if user_id == "participant-one" else "b")
        * 64,
    }


def fixture(participants=1):
    release = DEFAULT_STUDY_REGISTRY.release(RECORDING_FEASIBILITY_ID)
    users = {"session-one": user("participant-one", ACCOUNT_ONE)}
    if participants == 2:
        users["session-two"] = user("participant-two", ACCOUNT_TWO)
    by_id = {value["_id"]: value for value in users.values()}
    states = {
        user_id: {
            "document_type": "brainstem_study_participant_state",
            "user_id": user_id,
            "offerings": {
                RECORDING_FEASIBILITY_ID: {
                    "enrollment": enrollment(release, user_id)
                }
            },
        }
        for user_id in by_id
    }
    clock = [NOW]
    dao = StudyDao(states)
    operations = Operations(release)
    auth = Auth(users)
    users_dao = UsersDao(by_id)
    enrollments = Enrollments()
    services = {}
    for token, current_user in users.items():
        services[token] = StudyRecurringService(
            auth,
            users_dao,
            dao,
            enrollments,
            operations,
            DEFAULT_STUDY_REGISTRY,
            feature_enabled=True,
            clock=lambda: clock[0],
            id_factory=lambda: "c" * 32,
            nonce_factory=lambda: "n" * 43,
            lease_factory=lambda: "l" * 43,
        )
    return {
        "services": services,
        "service": services["session-one"],
        "users": by_id,
        "dao": dao,
        "operations": operations,
        "users_dao": users_dao,
        "enrollments": enrollments,
        "clock": clock,
        "release": release,
    }


def sign(account, message):
    return Account.sign_message(
        encode_defunct(text=message), account.key
    ).signature.hex()


def action(current, action_name, account=ACCOUNT_ONE, settings=None, token="session-one"):
    service = current["services"][token]
    challenge = service.challenge(
        token,
        ORIGIN,
        RECORDING_FEASIBILITY_ID,
        action_name,
        deepcopy(SETTINGS if action_name == "activate" and settings is None else settings),
    )
    return service.apply(
        token,
        ORIGIN,
        RECORDING_FEASIBILITY_ID,
        challenge["challengeId"],
        sign(account, challenge["message"]),
    )


def authorize(current, settings=None):
    return action(current, "activate", settings=settings)


def private(current, user_id="participant-one"):
    return current["dao"].states[user_id]["offerings"][
        RECORDING_FEASIBILITY_ID
    ]


def claim(current, lease_id="l" * 43, accepted_at=NOW + 1, count=2, now=None):
    return current["service"].claim(
        "participant-one",
        RECORDING_FEASIBILITY_ID,
        latest_source_accepted_at=accepted_at,
        new_eligible_recordings=count,
        lease_id=lease_id,
        now=current["clock"][0] if now is None else now,
    )


def test_signed_study_binding_is_exact_private_and_separate_from_personal_authority():
    current = fixture()
    status = authorize(current)
    binding = status["binding"]
    assert set(binding) == {
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
    assert binding["proposalId"] == PROPOSAL_ID
    assert binding["permitId"] == PERMIT_ID
    assert binding["releaseSha256"] == current["release"]["releaseSha256"]
    assert status["settings"] == SETTINGS
    stored = private(current)
    assert len(stored["recurringEvidence"]) == 1
    assert stored["recurringEvidence"][0]["signature"]
    assert stored["recurringAuthorization"]["lease"] is None
    assert "lease" not in status
    exposed = json.dumps(status)
    for forbidden in (
        "participant-one",
        ACCOUNT_ONE.address,
        "signature",
        "nonce",
        "personal-insight",
    ):
        assert forbidden not in exposed


def test_signature_chain_tamper_origin_and_current_identity_fail_closed():
    current = fixture()
    authorize(current)
    action(current, "pause", settings=None)
    assert len(private(current)["recurringEvidence"]) == 2

    tampered = fixture()
    authorize(tampered)
    private(tampered)["recurringEvidence"][0]["challenge"]["binding"][
        "referenceSha256"
    ] = "f" * 64
    with pytest.raises(StudyRecurringError, match="evidence_invalid"):
        tampered["service"].status(
            "session-one", ORIGIN, RECORDING_FEASIBILITY_ID
        )

    with pytest.raises(Exception):
        current["service"].status(
            "session-one", "https://evil.example", RECORDING_FEASIBILITY_ID
        )

    current["users"]["participant-one"]["public_address"] = ACCOUNT_TWO.address
    with pytest.raises(StudyRecurringError):
        current["service"].status(
            "session-one", ORIGIN, RECORDING_FEASIBILITY_ID
        )


@pytest.mark.parametrize(
    ("mutation", "reason"),
    (
        ("insufficient", "insufficient_data_change"),
        ("expiry", "expired"),
        ("consent", "consent_unavailable"),
        ("lifecycle", "study_recurring_authority_unavailable"),
        ("renewal", "renewal_required"),
        ("state_sha", "renewal_required"),
    ),
)
def test_due_claim_revalidates_threshold_expiry_consent_lifecycle_and_version(
    mutation, reason
):
    current = fixture()
    authorize(current)
    count = 2
    now = NOW + 1
    if mutation == "insufficient":
        count = 1
    elif mutation == "expiry":
        now = SETTINGS["expiresAt"]
    elif mutation == "consent":
        current["users"]["participant-one"]["usage_flag"] = "REJECTED"
    elif mutation == "lifecycle":
        current["operations"].state["lifecycleState"] = "paused"
    elif mutation == "renewal":
        current["operations"].renewal_required = True
    else:
        current["operations"].state["stateSha256"] = "f" * 64

    result = claim(current, count=count, now=now)
    assert result == {"status": "not_due", "reason": reason, "capability": None}
    assert private(current)["recurringAuthorization"]["lease"] is None


def test_claim_requires_reminder_authority_before_callback_can_run():
    current = fixture()
    authorize(current)
    current["operations"].denied_capabilities.add("reminder")
    result = claim(current)
    assert result == {
        "status": "not_due",
        "reason": "study_recurring_authority_unavailable",
        "capability": None,
    }
    assert private(current)["recurringAuthorization"]["lease"] is None


@pytest.mark.parametrize("source", ("users_dao", "enrollments", "operations"))
def test_authority_source_outage_is_unavailable_not_not_due(source):
    current = fixture()
    authorize(current)
    current[source].error = RuntimeError("source unavailable")
    with pytest.raises(StudyRecurringError) as caught:
        claim(current)
    assert caught.value.status_code == 503
    assert private(current)["recurringAuthorization"]["lease"] is None


def test_authority_source_outage_before_completion_keeps_lease_and_no_outbox():
    current = fixture()
    authorize(current)
    claimed = claim(current)
    current["operations"].error = RuntimeError("source unavailable")
    with pytest.raises(StudyRecurringError) as caught:
        current["service"].complete(
            "participant-one",
            RECORDING_FEASIBILITY_ID,
            claimed["capability"]["lease"],
            claimed["capability"]["runKey"],
        )
    assert caught.value.status_code == 503
    assert private(current)["recurringAuthorization"]["lease"] is not None
    assert "recurringOutbox" not in private(current)


def test_operation_state_change_during_capability_check_blocks_callback():
    current = fixture()
    authorize(current)
    callbacks = []
    original_claim = current["service"].claim

    def claim_then_change_during_revalidation(*args, **kwargs):
        result = original_claim(*args, **kwargs)
        current["operations"].mutate_during_allowed = True
        return result

    current["service"].claim = claim_then_change_during_revalidation
    worker = GeneratedStudyRecurringWorker(
        current["service"],
        lambda: ["participant-one"],
        lambda *_args: {
            "latestSourceAcceptedAt": NOW + 1,
            "newEligibleRecordings": 2,
        },
        lambda *args: callbacks.append(args),
        recurring_enabled=True,
        generated_worker_enabled=True,
        external_delivery_enabled=False,
    )

    receipt = worker.tick(RECORDING_FEASIBILITY_ID)

    assert receipt["claimedCount"] == 1
    assert receipt["completedCount"] == 0
    assert receipt["skippedCount"] == 1
    assert callbacks == []
    assert private(current)["recurringAuthorization"]["lease"] is None
    assert "recurringOutbox" not in private(current)


def test_cadence_and_rolling_thirty_day_budget_are_enforced():
    current = fixture()
    settings = {**SETTINGS, "maximumRunsPer30Days": 1}
    authorize(current, settings)
    first = claim(current)
    current["clock"][0] = NOW + 2
    current["service"].complete(
        "participant-one",
        RECORDING_FEASIBILITY_ID,
        first["capability"]["lease"],
        first["capability"]["runKey"],
    )
    cadence = claim(current, lease_id="m" * 43, accepted_at=NOW + 3, now=NOW + 3)
    assert cadence["reason"] == "cadence"
    budget = claim(
        current,
        lease_id="m" * 43,
        accepted_at=NOW + 8 * 86400,
        now=NOW + 8 * 86400,
    )
    assert budget["reason"] == "budget"


def test_signed_renewal_rebinds_exact_authority_and_clears_old_outbox():
    current = fixture()
    authorize(current)
    first = claim(current)
    current["clock"][0] = NOW + 2
    current["service"].complete(
        "participant-one",
        RECORDING_FEASIBILITY_ID,
        first["capability"]["lease"],
        first["capability"]["runKey"],
    )
    assert len(private(current)["recurringOutbox"]) == 1
    current["operations"].state["stateSha256"] = "f" * 64

    renewed = authorize(current)

    assert renewed["binding"]["operationStateSha256"] == "f" * 64
    assert renewed["revision"] == 2
    assert len(private(current)["recurringEvidence"]) == 2
    assert "recurringOutbox" not in private(current)


def test_duplicate_claims_expiry_takeover_completion_retry_and_outbox_dedup():
    current = fixture()
    authorize(current)
    first = claim(current, lease_id="l" * 43)
    replay = claim(current, lease_id="l" * 43)
    duplicate = claim(current, lease_id="m" * 43)
    assert replay == first
    assert duplicate["reason"] == "leased"

    takeover = claim(current, lease_id="m" * 43, now=NOW + 301)
    assert takeover["capability"]["runKey"] == first["capability"]["runKey"]
    current["clock"][0] = NOW + 302
    with pytest.raises(StudyRecurringError, match="lease_unavailable"):
        current["service"].complete(
            "participant-one",
            RECORDING_FEASIBILITY_ID,
            first["capability"]["lease"],
            first["capability"]["runKey"],
        )
    completed = current["service"].complete(
        "participant-one",
        RECORDING_FEASIBILITY_ID,
        takeover["capability"]["lease"],
        takeover["capability"]["runKey"],
    )
    retried = current["service"].complete(
        "participant-one",
        RECORDING_FEASIBILITY_ID,
        takeover["capability"]["lease"],
        takeover["capability"]["runKey"],
    )
    assert retried == completed
    assert len(private(current)["recurringOutbox"]) == 1


@pytest.mark.parametrize("action_name", ("pause", "revoke", "delete"))
def test_participant_control_wins_over_completion_in_same_document(action_name):
    current = fixture()
    authorize(current)
    claimed = claim(current)
    action(current, action_name, settings=None)
    current["clock"][0] = NOW + 2
    with pytest.raises(StudyRecurringError):
        current["service"].complete(
            "participant-one",
            RECORDING_FEASIBILITY_ID,
            claimed["capability"]["lease"],
            claimed["capability"]["runKey"],
        )
    assert "recurringOutbox" not in private(current)


def test_renewal_between_callback_and_completion_aborts_without_outbox():
    current = fixture()
    authorize(current)

    def renew_during_callback(user_id, offering_id, _capability):
        def renew(state):
            private_state = state["offerings"][offering_id]
            private_state["enrollment"]["state"] = "renewal_required"
            block_recurring_for_renewal(private_state)
            return state

        current["dao"].mutate_state(user_id, renew)

    worker = GeneratedStudyRecurringWorker(
        current["service"],
        lambda: ["participant-one"],
        lambda _user_id, _offering_id: {
            "latestSourceAcceptedAt": NOW + 1,
            "newEligibleRecordings": 2,
        },
        renew_during_callback,
        recurring_enabled=True,
        generated_worker_enabled=True,
        external_delivery_enabled=False,
    )
    with pytest.raises(StudyRecurringError):
        worker.tick(RECORDING_FEASIBILITY_ID)
    assert "recurringOutbox" not in private(current)
    assert private(current)["recurringAuthorization"]["lease"] is None


def test_cas_retry_does_not_duplicate_evidence_claim_completion_or_notification():
    current = fixture()
    current["dao"].conflict_once = True
    authorize(current)
    assert len(private(current)["recurringEvidence"]) == 1
    current["dao"].conflict_once = True
    claimed = claim(current)
    current["dao"].conflict_once = True
    current["clock"][0] = NOW + 2
    current["service"].complete(
        "participant-one",
        RECORDING_FEASIBILITY_ID,
        claimed["capability"]["lease"],
        claimed["capability"]["runKey"],
    )
    assert len(private(current)["recurringAuthorization"]["completions"]) == 1
    assert len(private(current)["recurringOutbox"]) == 1


def test_outbox_is_private_redacted_bounded_readable_and_deletable():
    current = fixture(participants=2)
    authorize(current)
    action(
        current,
        "activate",
        account=ACCOUNT_TWO,
        token="session-two",
    )
    claimed = claim(current)
    current["clock"][0] = NOW + 2
    completion = current["service"].complete(
        "participant-one",
        RECORDING_FEASIBILITY_ID,
        claimed["capability"]["lease"],
        claimed["capability"]["runKey"],
    )
    assert completion["notificationQueued"] is True
    notification_id = completion["notificationId"]
    outbox = current["service"].list_outbox(
        "session-one", ORIGIN, RECORDING_FEASIBILITY_ID
    )
    serialized = json.dumps(outbox)
    assert outbox["items"][0]["state"] == "unread"
    for forbidden in (
        "participant-one",
        ACCOUNT_ONE.address,
        claimed["capability"]["runKey"],
        "jobId",
        "health",
        "condition",
        "diagnosis",
        "device",
    ):
        assert forbidden not in serialized
    assert current["services"]["session-two"].list_outbox(
        "session-two", ORIGIN, RECORDING_FEASIBILITY_ID
    )["items"] == []
    read = current["service"].acknowledge(
        "session-one", ORIGIN, RECORDING_FEASIBILITY_ID, notification_id
    )
    assert read["state"] == "read"
    assert current["service"].acknowledge(
        "session-one", ORIGIN, RECORDING_FEASIBILITY_ID, notification_id
    ) == read
    current["service"].delete_notification(
        "session-one", ORIGIN, RECORDING_FEASIBILITY_ID, notification_id
    )
    assert current["service"].list_outbox(
        "session-one", ORIGIN, RECORDING_FEASIBILITY_ID
    )["items"] == []

    authorize_again = fixture()
    authorize(authorize_again)
    private(authorize_again)["recurringOutbox"] = [
        {
            "schema": "brainstem.study-recurring-notification/v1",
            "notificationId": "{:064x}".format(index),
            "messageKey": "study_result_ready",
            "state": "unread",
            "createdAt": NOW,
            "readAt": None,
        }
        for index in range(MAX_OUTBOX)
    ]
    full_claim = claim(authorize_again)
    assert full_claim == {
        "status": "not_due",
        "reason": "outbox_full",
        "capability": None,
    }
    assert private(authorize_again)["recurringAuthorization"]["lease"] is None


def test_full_unread_outbox_backpressures_retries_before_callback_or_lease():
    current = fixture()
    authorize(current)
    stale_claim = claim(current)
    assert stale_claim["status"] == "claimed"
    private(current)["recurringOutbox"] = [
        {
            "schema": "brainstem.study-recurring-notification/v1",
            "notificationId": "{:064x}".format(index),
            "messageKey": "study_result_ready",
            "state": "unread",
            "createdAt": NOW,
            "readAt": None,
        }
        for index in range(MAX_OUTBOX)
    ]
    current["clock"][0] = NOW + 301
    callbacks = []
    worker = GeneratedStudyRecurringWorker(
        current["service"],
        lambda: ["participant-one"],
        lambda *_args: {
            "latestSourceAcceptedAt": NOW + 1,
            "newEligibleRecordings": 2,
        },
        lambda *args: callbacks.append(args),
        recurring_enabled=True,
        generated_worker_enabled=True,
        external_delivery_enabled=False,
    )

    receipts = [worker.tick(RECORDING_FEASIBILITY_ID) for _index in range(2)]

    assert all(receipt["claimedCount"] == 0 for receipt in receipts)
    assert all(receipt["completedCount"] == 0 for receipt in receipts)
    assert all(receipt["skippedCount"] == 1 for receipt in receipts)
    assert callbacks == []
    assert private(current)["recurringAuthorization"]["lease"] is None
    assert len(private(current)["recurringOutbox"]) == MAX_OUTBOX


def test_outbox_filling_after_claim_is_revalidated_before_callback():
    current = fixture()
    authorize(current)
    callbacks = []
    original_claim = current["service"].claim

    def claim_then_fill_outbox(*args, **kwargs):
        result = original_claim(*args, **kwargs)
        private(current)["recurringOutbox"] = [
            {
                "schema": "brainstem.study-recurring-notification/v1",
                "notificationId": "{:064x}".format(index),
                "messageKey": "study_result_ready",
                "state": "unread",
                "createdAt": NOW,
                "readAt": None,
            }
            for index in range(MAX_OUTBOX)
        ]
        return result

    current["service"].claim = claim_then_fill_outbox
    worker = GeneratedStudyRecurringWorker(
        current["service"],
        lambda: ["participant-one"],
        lambda *_args: {
            "latestSourceAcceptedAt": NOW + 1,
            "newEligibleRecordings": 2,
        },
        lambda *args: callbacks.append(args),
        recurring_enabled=True,
        generated_worker_enabled=True,
        external_delivery_enabled=False,
    )

    receipt = worker.tick(RECORDING_FEASIBILITY_ID)

    assert receipt["claimedCount"] == 1
    assert receipt["completedCount"] == 0
    assert callbacks == []
    assert private(current)["recurringAuthorization"]["lease"] is None


def test_callback_filling_outbox_records_terminal_completion_without_retry():
    current = fixture()
    authorize(current)
    callbacks = []
    completion_responses = []
    existing = [
        {
            "schema": "brainstem.study-recurring-notification/v1",
            "notificationId": "{:064x}".format(index),
            "messageKey": "study_result_ready",
            "state": "unread",
            "createdAt": NOW,
            "readAt": None,
        }
        for index in range(MAX_OUTBOX)
    ]
    original_complete = current["service"].complete

    def fill_outbox(*args):
        callbacks.append(args)
        private(current)["recurringOutbox"] = deepcopy(existing)

    def capture_completion(*args, **kwargs):
        response = original_complete(*args, **kwargs)
        completion_responses.append(response)
        return response

    current["service"].complete = capture_completion
    worker = GeneratedStudyRecurringWorker(
        current["service"],
        lambda: ["participant-one"],
        lambda *_args: {
            "latestSourceAcceptedAt": NOW + 1,
            "newEligibleRecordings": 2,
        },
        fill_outbox,
        recurring_enabled=True,
        generated_worker_enabled=True,
        external_delivery_enabled=False,
    )

    first = worker.tick(RECORDING_FEASIBILITY_ID)
    capability = callbacks[0][2]
    authorization = private(current)["recurringAuthorization"]

    assert first["claimedCount"] == 1
    assert first["completedCount"] == 1
    assert len(callbacks) == 1
    assert authorization["lease"] is None
    assert authorization["lastSourceAcceptedAt"] == NOW + 1
    assert len(authorization["completions"]) == 1
    assert authorization["completions"][0]["notificationQueued"] is False
    assert authorization["completions"][0]["notificationId"] is None
    assert completion_responses == [
        {
            "schema": "brainstem.study-recurring-completion/v1",
            "status": "completed",
            "notificationQueued": False,
            "notificationId": None,
            "completedAt": NOW,
        }
    ]
    assert private(current)["recurringOutbox"] == existing

    assert original_complete(
        "participant-one",
        RECORDING_FEASIBILITY_ID,
        capability["lease"],
        capability["runKey"],
    ) == completion_responses[0]
    second = worker.tick(RECORDING_FEASIBILITY_ID)

    assert second["claimedCount"] == 0
    assert second["completedCount"] == 0
    assert second["skippedCount"] == 1
    assert len(callbacks) == 1
    assert private(current)["recurringAuthorization"]["lease"] is None
    assert private(current)["recurringOutbox"] == existing


@pytest.mark.parametrize("access", ("list", "read"))
@pytest.mark.parametrize(
    "invalidation", ("consent", "wallet", "pause", "operation")
)
def test_outbox_visibility_and_read_fail_closed_after_authority_invalidation(
    access, invalidation
):
    current = fixture()
    authorize(current)
    claimed = claim(current)
    current["clock"][0] = NOW + 2
    completion = current["service"].complete(
        "participant-one",
        RECORDING_FEASIBILITY_ID,
        claimed["capability"]["lease"],
        claimed["capability"]["runKey"],
    )
    if invalidation == "consent":
        current["users"]["participant-one"]["usage_flag"] = "REJECTED"
    elif invalidation == "wallet":
        current["users"]["participant-one"][
            "public_address"
        ] = ACCOUNT_TWO.address
    elif invalidation == "pause":
        action(current, "pause", settings=None)
    else:
        current["operations"].denied_capabilities.add("reminder")

    with pytest.raises(StudyRecurringError) as caught:
        if access == "list":
            current["service"].list_outbox(
                "session-one", ORIGIN, RECORDING_FEASIBILITY_ID
            )
        else:
            current["service"].acknowledge(
                "session-one",
                ORIGIN,
                RECORDING_FEASIBILITY_ID,
                completion["notificationId"],
            )

    assert caught.value.status_code == 409
    assert "recurringOutbox" not in private(current)


def test_outbox_source_outage_exposes_nothing_without_destroying_unread_item():
    current = fixture()
    authorize(current)
    claimed = claim(current)
    current["clock"][0] = NOW + 2
    current["service"].complete(
        "participant-one",
        RECORDING_FEASIBILITY_ID,
        claimed["capability"]["lease"],
        claimed["capability"]["runKey"],
    )
    current["operations"].error = RuntimeError("source unavailable")

    with pytest.raises(StudyRecurringError) as caught:
        current["service"].list_outbox(
            "session-one", ORIGIN, RECORDING_FEASIBILITY_ID
        )

    assert caught.value.status_code == 503
    assert len(private(current)["recurringOutbox"]) == 1
    assert private(current)["recurringOutbox"][0]["state"] == "unread"


def test_outbox_delete_remains_opaque_cleanup_after_authority_invalidation():
    current = fixture()
    authorize(current)
    claimed = claim(current)
    current["clock"][0] = NOW + 2
    completion = current["service"].complete(
        "participant-one",
        RECORDING_FEASIBILITY_ID,
        claimed["capability"]["lease"],
        claimed["capability"]["runKey"],
    )
    current["users"]["participant-one"]["usage_flag"] = "REJECTED"

    assert (
        current["service"].delete_notification(
            "session-one",
            ORIGIN,
            RECORDING_FEASIBILITY_ID,
            completion["notificationId"],
        )
        is None
    )
    assert "recurringOutbox" not in private(current)


def test_withdrawal_deletion_and_renewal_helpers_clear_private_capabilities():
    current = fixture()
    authorize(current)
    claimed = claim(current)
    private(current)["recurringOutbox"] = [{"private": True}]
    block_recurring_for_renewal(private(current))
    assert private(current)["recurringAuthorization"]["lease"] is None
    assert "recurringChallenge" not in private(current)
    assert "recurringOutbox" not in private(current)

    scrub_recurring(private(current), state="revoked", now=NOW + 2)
    assert set(private(current)) == {"enrollment", "recurringTombstone"}
    assert private(current)["recurringTombstone"]["state"] == "revoked"
    assert claimed["capability"]["runKey"] not in json.dumps(private(current))
    scrub_recurring(private(current), state="deleted", now=NOW + 3)
    assert private(current)["recurringTombstone"]["state"] == "deleted"
    assert private(current)["recurringTombstone"]["revision"] == 1


def test_evidence_bound_reserves_the_final_slot_for_revocation():
    current = fixture()
    authorize(current)
    for index in range(30):
        action(
            current,
            "pause" if index % 2 == 0 else "resume",
            settings=None,
        )
    assert len(private(current)["recurringEvidence"]) == 31
    with pytest.raises(StudyRecurringError, match="evidence_limit"):
        action(current, "pause", settings=None)
    revoked = action(current, "revoke", settings=None)
    assert revoked["state"] == "revoked"
    assert len(private(current)["recurringEvidence"]) == 32


def test_generated_worker_requires_all_gates_calls_only_injected_local_callback_once():
    current = fixture()
    authorize(current)
    calls = []
    candidates = []
    facts = []

    def candidate_source():
        candidates.append(True)
        return ["participant-one"]

    def fact_source(user_id, offering_id):
        facts.append((user_id, offering_id))
        return {
            "latestSourceAcceptedAt": NOW + 1,
            "newEligibleRecordings": 2,
        }

    for gates in (
        (False, True, False),
        (True, False, False),
        (True, True, True),
    ):
        worker = GeneratedStudyRecurringWorker(
            current["service"],
            candidate_source,
            fact_source,
            lambda *args: calls.append(args),
            recurring_enabled=gates[0],
            generated_worker_enabled=gates[1],
            external_delivery_enabled=gates[2],
        )
        with pytest.raises(StudyRecurringError, match="worker_disabled"):
            worker.tick(RECORDING_FEASIBILITY_ID)
    assert candidates == []
    assert facts == []
    assert calls == []

    worker = GeneratedStudyRecurringWorker(
        current["service"],
        candidate_source,
        fact_source,
        lambda *args: calls.append(args),
        recurring_enabled=True,
        generated_worker_enabled=True,
        external_delivery_enabled=False,
    )
    receipt = worker.tick(RECORDING_FEASIBILITY_ID)
    assert receipt["claimedCount"] == receipt["completedCount"] == 1
    assert len(calls) == 1
    assert len(private(current)["recurringOutbox"]) == 1


def test_generated_tick_claims_completes_and_notifies_at_most_one_participant():
    current = fixture(participants=2)
    authorize(current)
    action(
        current,
        "activate",
        account=ACCOUNT_TWO,
        token="session-two",
    )
    calls = []
    worker = GeneratedStudyRecurringWorker(
        current["service"],
        lambda: ["participant-one", "participant-two"],
        lambda *_args: {
            "latestSourceAcceptedAt": NOW + 1,
            "newEligibleRecordings": 2,
        },
        lambda *args: calls.append(args),
        recurring_enabled=True,
        generated_worker_enabled=True,
        external_delivery_enabled=False,
    )
    receipt = worker.tick(RECORDING_FEASIBILITY_ID)
    assert receipt == {
        "schema": "brainstem.study-recurring-generated-tick/v1",
        "inspectedCount": 1,
        "claimedCount": 1,
        "completedCount": 1,
        "skippedCount": 0,
    }
    assert len(calls) == 1
    assert len(private(current, "participant-one")["recurringOutbox"]) == 1
    assert "recurringOutbox" not in private(current, "participant-two")


def test_worker_crash_leaves_retryable_lease_and_base_flags_remain_false():
    current = fixture()
    authorize(current)

    def crash(*_args):
        raise RuntimeError("generated callback crashed")

    worker = GeneratedStudyRecurringWorker(
        current["service"],
        lambda: ["participant-one"],
        lambda *_args: {
            "latestSourceAcceptedAt": NOW + 1,
            "newEligibleRecordings": 2,
        },
        crash,
        recurring_enabled=True,
        generated_worker_enabled=True,
        external_delivery_enabled=False,
    )
    with pytest.raises(RuntimeError, match="callback crashed"):
        worker.tick(RECORDING_FEASIBILITY_ID)
    assert private(current)["recurringAuthorization"]["lease"] is not None
    assert "recurringOutbox" not in private(current)

    sample = ConfigParser()
    sample.read("sample.ini")
    section = sample["brainstem_recurring_insights"]
    assert section.getboolean("enabled") is False
    assert section.getboolean("generated_worker_enabled") is False
    assert section.getboolean("external_delivery_enabled") is False
