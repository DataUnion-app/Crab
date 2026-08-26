from copy import deepcopy
import hashlib
import threading

from eth_account import Account
from eth_account.messages import encode_defunct
import pytest

from commands.dataunions.brainstem.study_activation import (
    StudyActivationError,
    StudyActivationService,
    public_permit,
)
from commands.dataunions.brainstem.study_proposals import (
    StudyProposalConflict,
    StudyProposalWorkflow,
)
from commands.dataunions.brainstem.study_registry import (
    APDET_RETROSPECTIVE_ID,
    APDET_RETROSPECTIVE_RELEASE_SHA256,
    DEFAULT_STUDY_REGISTRY,
    RECORDING_FEASIBILITY_ID,
)
from commands.dataunions.studies.registry import StudyRegistryError, content_sha256
from dao.study_activation_dao import StudyActivationStateError


NOW = 1785595200
ORIGIN = "https://desci.example"
AUTHOR = Account.from_key("0x" + "11" * 32)
REVIEWERS = [Account.from_key("0x" + value * 32) for value in ("21", "22", "23", "24")]
OPERATOR = Account.from_key("0x" + "31" * 32)
WRONG = Account.from_key("0x" + "41" * 32)
DOMAINS = ("scientific", "privacy", "security", "ethics")


def payload(**changes):
    release = DEFAULT_STUDY_REGISTRY.release(RECORDING_FEASIBILITY_ID)
    value = {
        "title": "Everyday resting recording follow-up",
        "purpose": "Test a bounded and reproducible feasibility question using generated records.",
        "population": "Adults who voluntarily complete the exact candidate participant flow.",
        "participantBurden": "One ordinary five-minute resting recording each day for fourteen days.",
        "recordings": "Prospective Brainstem resting R-R recordings with verified capture time.",
        "surveyOutline": "Bounded self-reported adult and long-term health context questions.",
        "schedule": "Fourteen full UTC study days.",
        "endpoints": "Feasibility and within-participant repeatability of qualifying recordings.",
        "analysisPlan": "Run only a separately reviewed aggregate algorithm over a source-defined dataset view.",
        "retention": "Retain versioned study evidence under the disclosed candidate policy.",
        "resultReturnPlan": "Return only a reviewed plain-language aggregate study summary.",
        "sourcePapers": ["https://doi.org/10.1000/generated-example"],
        "conflicts": "No known conflicts for this generated local proposal.",
        "offeringId": release["offeringId"],
        "releaseVersion": release["releaseVersion"],
        "releaseSha256": release["releaseSha256"],
    }
    value.update(changes)
    return value


class ProposalDao:
    def __init__(self):
        self.docs = {}

    def create(self, document):
        self.docs[document["proposalId"]] = deepcopy(document)

    def get(self, proposal_id):
        return deepcopy(self.docs[proposal_id])

    def mutate(self, proposal_id, mutator):
        self.docs[proposal_id] = deepcopy(mutator(deepcopy(self.docs[proposal_id])))
        return deepcopy(self.docs[proposal_id])

    def list_owned(self, _author, _page, _per_page):
        return [], False

    def list_queue(self, _page, _per_page, _status=None):
        return [], False


class ActivationDao:
    def __init__(self):
        self.docs = {}
        self.lock = threading.Lock()

    def create_challenge(self, proposal_id, challenge, _now):
        with self.lock:
            document = self.docs.setdefault(
                proposal_id, {"challenges": {}, "permits": {}}
            )
            document["challenges"][challenge["challenge_id"]] = deepcopy(challenge)
        return deepcopy(challenge)

    def get_challenge(self, proposal_id, challenge_id):
        with self.lock:
            try:
                return deepcopy(self.docs[proposal_id]["challenges"][challenge_id])
            except KeyError as error:
                raise StudyActivationStateError("Activation challenge unavailable") from error

    def consume_challenge_and_create_permit(
        self,
        proposal_id,
        challenge_id,
        expected_bundle_sha256,
        permit,
        signature,
        now,
    ):
        with self.lock:
            challenge = self.docs[proposal_id]["challenges"][challenge_id]
            if challenge["consumed_at"] is not None:
                raise StudyActivationStateError("Activation challenge already used")
            if challenge["expires_at"] <= now:
                raise StudyActivationStateError("Activation challenge expired")
            if challenge["bundle_sha256"] != expected_bundle_sha256:
                raise StudyActivationStateError("Activation bundle changed")
            challenge["consumed_at"] = now
            challenge["permit_id"] = permit["permitId"]
            challenge["signature_sha256"] = hashlib.sha256(
                signature.encode("ascii")
            ).hexdigest()
            challenge["signature"] = signature
            self.docs[proposal_id]["permits"][permit["permitId"]] = deepcopy(permit)
            return deepcopy(permit)

    def get_permit(self, proposal_id, permit_id):
        with self.lock:
            try:
                return deepcopy(self.docs[proposal_id]["permits"][permit_id])
            except KeyError as error:
                raise StudyActivationStateError("Activation permit unavailable") from error

    def get_permit_evidence(self, proposal_id, permit_id):
        with self.lock:
            try:
                permit = self.docs[proposal_id]["permits"][permit_id]
                challenge = self.docs[proposal_id]["challenges"][
                    permit["challengeId"]
                ]
                return {
                    "permit": deepcopy(permit),
                    "challenge": deepcopy(challenge),
                }
            except KeyError as error:
                raise StudyActivationStateError(
                    "Activation permit evidence unavailable"
                ) from error


class Clock:
    def __init__(self, value=NOW):
        self.value = value

    def __call__(self):
        return self.value


def ids():
    counter = 0

    def factory(prefix=None):
        nonlocal counter
        counter += 1
        if prefix is None:
            return format(counter, "032x")
        return "{}_{}".format(prefix, format(counter, "x"))

    return factory


def reviewed_proposal(proposal_dao=None, proposal_payload=None):
    proposal_dao = proposal_dao or ProposalDao()
    flow = StudyProposalWorkflow(
        proposal_dao,
        clock=lambda: "2026-07-31T00:00:00Z",
        id_factory=ids(),
    )
    proposal = flow.create(AUTHOR.address, proposal_payload or payload())
    proposal_id = proposal["proposalId"]
    revision_id = proposal["currentRevisionId"]
    revision_sha256 = proposal["currentRevisionSha256"]
    flow.submit(proposal_id, AUTHOR.address, revision_id, revision_sha256)
    for domain, reviewer in zip(DOMAINS, REVIEWERS):
        flow.review(
            proposal_id,
            reviewer.address,
            domain,
            "approved",
            revision_id,
            revision_sha256,
            "The {} generated evidence approves this exact revision.".format(domain),
            content_sha256({"domain": domain, "fixture": "generated-only"}),
        )
    return proposal_dao, proposal_id, revision_id, revision_sha256


def service(proposal_dao, activation_dao=None, clock=None):
    return StudyActivationService(
        activation_dao or ActivationDao(),
        proposal_dao,
        DEFAULT_STUDY_REGISTRY,
        allowed_operators=[OPERATOR.address],
        allowed_origins=[ORIGIN],
        challenge_ttl=300,
        clock=clock or Clock(),
        nonce_factory=lambda: "generated-operator-nonce",
        id_factory=ids(),
    )


def challenge_for(current_service, proposal_id, revision_id, revision_sha256):
    return current_service.create_challenge(
        proposal_id,
        OPERATOR.address,
        ORIGIN,
        revision_id,
        revision_sha256,
    )


def sign(account, message):
    return Account.sign_message(
        encode_defunct(text=message), account.key
    ).signature.hex()


def test_generated_operator_creates_only_an_exact_zero_payment_permit():
    proposals, proposal_id, revision_id, revision_sha256 = reviewed_proposal()
    activations = ActivationDao()
    current = service(proposals, activations)
    challenge = challenge_for(current, proposal_id, revision_id, revision_sha256)
    bundle = challenge["bundle"]
    profile = bundle["activationProfile"]["content"]

    assert bundle["proposal"] == {
        "proposalId": proposal_id,
        "revisionId": revision_id,
        "revisionSha256": revision_sha256,
    }
    assert [item["domain"] for item in bundle["decisions"]] == sorted(DOMAINS)
    assert len({item["decisionSha256"] for item in bundle["decisions"]}) == 4
    assert bundle["release"]["releaseSha256"] == payload()["releaseSha256"]
    assert profile["datasetCapability"] == (
        "brainstem.study-export.recording-feasibility.v1"
    )
    assert profile["payment"] == {"currency": "none", "amountMinor": 0}
    assert profile["dataMode"] == "generated_only"
    assert "This does not recruit" in challenge["message"]
    assert "Activation Bundle SHA256: {}".format(bundle["bundleSha256"]) in challenge[
        "message"
    ]

    permit = current.apply(
        proposal_id,
        OPERATOR.address,
        ORIGIN,
        challenge["challengeId"],
        sign(OPERATOR, challenge["message"]),
    )
    assert permit["status"] == "permitted"
    assert permit["bundle"] == bundle
    assert permit["permitSha256"] == content_sha256(
        {key: value for key, value in permit.items() if key != "permitSha256"}
    )
    assert "signature" not in permit
    assert "message" not in permit
    assert len(permit["signedMessageSha256"]) == 64
    assert len(permit["operatorSignatureSha256"]) == 64
    assert {permit["status"]}.isdisjoint({"recruiting", "active"})
    assert len(activations.docs[proposal_id]["permits"]) == 1

    tampered = deepcopy(permit)
    tampered["status"] = "active"
    with pytest.raises(StudyActivationError, match="study_activation_permit_invalid"):
        public_permit(tampered)

    nested_tamper = deepcopy(permit)
    nested_tamper["bundle"]["release"]["releaseSha256"] = "f" * 64
    nested_tamper["permitSha256"] = content_sha256(
        {
            key: value
            for key, value in nested_tamper.items()
            if key != "permitSha256"
        }
    )
    with pytest.raises(StudyActivationError, match="study_activation_permit_invalid"):
        public_permit(nested_tamper)

    assert current.load_verified_permit(proposal_id, permit["permitId"]) == permit


def test_author_may_operate_only_after_four_independent_reviews():
    proposals, proposal_id, revision_id, revision_sha256 = reviewed_proposal()
    current = StudyActivationService(
        ActivationDao(),
        proposals,
        DEFAULT_STUDY_REGISTRY,
        allowed_operators=[AUTHOR.address],
        allowed_origins=[ORIGIN],
        challenge_ttl=300,
        clock=Clock(),
        nonce_factory=lambda: "generated-author-operator-nonce",
        id_factory=ids(),
    )

    challenge = current.create_challenge(
        proposal_id,
        AUTHOR.address,
        ORIGIN,
        revision_id,
        revision_sha256,
    )
    assert challenge["bundle"]["proposal"]["proposalId"] == proposal_id
    assert len(challenge["bundle"]["decisions"]) == len(DOMAINS)

    permit = current.apply(
        proposal_id,
        AUTHOR.address,
        ORIGIN,
        challenge["challengeId"],
        sign(AUTHOR, challenge["message"]),
    )
    assert permit["operatorId"] == AUTHOR.address.lower()


def test_retrospective_real_cohort_release_can_reach_operator_permit():
    proposal_payload = payload(
        offeringId=APDET_RETROSPECTIVE_ID,
        releaseVersion="1.0.0",
        releaseSha256=APDET_RETROSPECTIVE_RELEASE_SHA256,
    )
    proposals, proposal_id, revision_id, revision_sha256 = reviewed_proposal(
        proposal_payload=proposal_payload
    )

    challenge = challenge_for(
        service(proposals), proposal_id, revision_id, revision_sha256
    )

    assert challenge["bundle"]["release"]["offeringType"] == "retrospective_study"
    assert challenge["bundle"]["activationProfile"]["content"]["dataMode"] == (
        "real_cohort"
    )


def test_verified_loader_rejects_forged_rehashed_permit_and_private_evidence_loss():
    proposals, proposal_id, revision_id, revision_sha256 = reviewed_proposal()
    activations = ActivationDao()
    current = service(proposals, activations)
    challenge = challenge_for(current, proposal_id, revision_id, revision_sha256)
    signature = sign(OPERATOR, challenge["message"])
    permit = current.apply(
        proposal_id,
        OPERATOR.address,
        ORIGIN,
        challenge["challengeId"],
        signature,
    )
    document = activations.docs[proposal_id]
    stored_permit = document["permits"][permit["permitId"]]
    stored_challenge = document["challenges"][challenge["challengeId"]]

    original_release_sha256 = stored_permit["bundle"]["release"]["releaseSha256"]
    forged_release_sha256 = "f" * 64
    stored_permit["bundle"]["release"]["releaseSha256"] = forged_release_sha256
    unsigned_bundle = {
        key: value
        for key, value in stored_permit["bundle"].items()
        if key != "bundleSha256"
    }
    forged_bundle_sha256 = content_sha256(unsigned_bundle)
    stored_permit["bundle"]["bundleSha256"] = forged_bundle_sha256
    stored_permit["bundleSha256"] = forged_bundle_sha256
    stored_challenge["bundle"] = deepcopy(stored_permit["bundle"])
    stored_challenge["bundle_sha256"] = forged_bundle_sha256
    stored_challenge["message"] = stored_challenge["message"].replace(
        original_release_sha256, forged_release_sha256
    )
    stored_permit["signedMessageSha256"] = hashlib.sha256(
        stored_challenge["message"].encode("utf-8")
    ).hexdigest()
    stored_permit["permitSha256"] = content_sha256(
        {
            key: value
            for key, value in stored_permit.items()
            if key != "permitSha256"
        }
    )
    with pytest.raises(StudyActivationError, match="study_activation_evidence_invalid"):
        current.load_verified_permit(proposal_id, permit["permitId"])

    document["permits"][permit["permitId"]] = deepcopy(permit)
    document["challenges"].pop(challenge["challengeId"])
    with pytest.raises(
        StudyActivationError, match="study_activation_evidence_unavailable"
    ):
        current.load_verified_permit(proposal_id, permit["permitId"])


def test_verified_loader_rejects_corrupt_private_signature_evidence():
    proposals, proposal_id, revision_id, revision_sha256 = reviewed_proposal()
    activations = ActivationDao()
    current = service(proposals, activations)
    challenge = challenge_for(current, proposal_id, revision_id, revision_sha256)
    permit = current.apply(
        proposal_id,
        OPERATOR.address,
        ORIGIN,
        challenge["challengeId"],
        sign(OPERATOR, challenge["message"]),
    )
    stored = activations.docs[proposal_id]["challenges"][challenge["challengeId"]]
    stored["signature"] = "0x" + "0" * 130
    stored["signature_sha256"] = hashlib.sha256(
        stored["signature"].encode("ascii")
    ).hexdigest()
    with pytest.raises(StudyActivationError, match="study_activation_evidence_invalid"):
        current.load_verified_permit(proposal_id, permit["permitId"])


def test_verified_loader_rejects_rehashed_unsigned_permit_timestamp():
    proposals, proposal_id, revision_id, revision_sha256 = reviewed_proposal()
    activations = ActivationDao()
    current = service(proposals, activations)
    challenge = challenge_for(current, proposal_id, revision_id, revision_sha256)
    permit = current.apply(
        proposal_id,
        OPERATOR.address,
        ORIGIN,
        challenge["challengeId"],
        sign(OPERATOR, challenge["message"]),
    )
    stored = activations.docs[proposal_id]["permits"][permit["permitId"]]
    stored["permittedAt"] = "2026-08-02T00:00:00Z"
    stored["permitSha256"] = content_sha256(
        {key: value for key, value in stored.items() if key != "permitSha256"}
    )
    with pytest.raises(StudyActivationError, match="study_activation_evidence_invalid"):
        current.load_verified_permit(proposal_id, permit["permitId"])


def test_verified_loader_enforces_current_operator_origin_and_chain_policy():
    proposals, proposal_id, revision_id, revision_sha256 = reviewed_proposal()

    def create_with(account, origin, chain_id):
        activations = ActivationDao()
        creator = StudyActivationService(
            activations,
            proposals,
            DEFAULT_STUDY_REGISTRY,
            allowed_operators=[account.address],
            allowed_origins=[origin],
            chain_id=chain_id,
            clock=Clock(),
            nonce_factory=lambda: "generated-policy-nonce",
            id_factory=ids(),
        )
        challenge = creator.create_challenge(
            proposal_id,
            account.address,
            origin,
            revision_id,
            revision_sha256,
        )
        permit = creator.apply(
            proposal_id,
            account.address,
            origin,
            challenge["challengeId"],
            sign(account, challenge["message"]),
        )
        return activations, permit

    activations, permit = create_with(WRONG, ORIGIN, 11155420)
    current_policy = StudyActivationService(
        activations,
        proposals,
        DEFAULT_STUDY_REGISTRY,
        allowed_operators=[OPERATOR.address],
        allowed_origins=[ORIGIN],
    )
    with pytest.raises(StudyActivationError, match="study_operator_forbidden"):
        current_policy.load_verified_permit(proposal_id, permit["permitId"])

    activations, permit = create_with(
        OPERATOR, "https://old-origin.example", 11155420
    )
    current_policy = StudyActivationService(
        activations,
        proposals,
        DEFAULT_STUDY_REGISTRY,
        allowed_operators=[OPERATOR.address],
        allowed_origins=[ORIGIN],
        chain_id=11155420,
    )
    with pytest.raises(StudyActivationError, match="study_operator_origin_forbidden"):
        current_policy.load_verified_permit(proposal_id, permit["permitId"])

    activations, permit = create_with(OPERATOR, ORIGIN, 1)
    chain_policy = StudyActivationService(
        activations,
        proposals,
        DEFAULT_STUDY_REGISTRY,
        allowed_operators=[OPERATOR.address],
        allowed_origins=[ORIGIN],
        chain_id=11155420,
    )
    with pytest.raises(StudyActivationError, match="study_activation_evidence_invalid"):
        chain_policy.load_verified_permit(proposal_id, permit["permitId"])


@pytest.mark.parametrize(
    "storage_error,status",
    [
        ("Activation challenge capacity reached", 409),
        ("Activation storage unavailable", 503),
    ],
)
def test_challenge_storage_failures_are_translated_fail_closed(storage_error, status):
    proposals, proposal_id, revision_id, revision_sha256 = reviewed_proposal()

    class FailingActivationDao(ActivationDao):
        def create_challenge(self, _proposal_id, _challenge, _now):
            raise StudyActivationStateError(storage_error)

    current = service(proposals, FailingActivationDao())
    with pytest.raises(
        StudyActivationError, match="study_activation_challenge_unavailable"
    ) as raised:
        challenge_for(current, proposal_id, revision_id, revision_sha256)
    assert raised.value.status_code == status


@pytest.mark.parametrize("state", ["draft", "partial", "changes_requested"])
def test_incomplete_or_negative_review_state_is_not_a_permit_candidate(state):
    proposals = ProposalDao()
    flow = StudyProposalWorkflow(
        proposals,
        clock=lambda: "2026-07-31T00:00:00Z",
        id_factory=ids(),
    )
    proposal = flow.create(AUTHOR.address, payload())
    proposal_id = proposal["proposalId"]
    revision_id = proposal["currentRevisionId"]
    revision_sha256 = proposal["currentRevisionSha256"]
    if state != "draft":
        flow.submit(proposal_id, AUTHOR.address, revision_id, revision_sha256)
        decision = "changes_requested" if state == "changes_requested" else "approved"
        flow.review(
            proposal_id,
            REVIEWERS[0].address,
            "scientific",
            decision,
            revision_id,
            revision_sha256,
            "This generated decision intentionally leaves review incomplete.",
            content_sha256({"state": state}),
        )
    with pytest.raises(StudyActivationError, match="study_not_permit_candidate"):
        challenge_for(service(proposals), proposal_id, revision_id, revision_sha256)


def test_unregistered_release_commitment_cannot_become_a_permit_candidate():
    proposals, proposal_id, revision_id, revision_sha256 = reviewed_proposal()
    revision = proposals.docs[proposal_id]["revisions"][-1]
    revision["releaseSha256"] = "f" * 64
    revision["revisionSha256"] = content_sha256(
        {key: value for key, value in revision.items() if key != "revisionSha256"}
    )
    proposals.docs[proposal_id]["currentRevisionSha256"] = revision["revisionSha256"]
    for review in proposals.docs[proposal_id]["reviews"]:
        review["revisionSha256"] = revision["revisionSha256"]
        review["decisionSha256"] = content_sha256(
            {key: value for key, value in review.items() if key != "decisionSha256"}
        )

    with pytest.raises(StudyRegistryError, match="offering_release_unknown"):
        challenge_for(
            service(proposals),
            proposal_id,
            revision_id,
            revision["revisionSha256"],
        )


@pytest.mark.parametrize("collapse", ["reused_reviewer", "author_self_review"])
def test_reviewer_identity_collapse_is_rechecked_before_challenge(collapse):
    proposals, proposal_id, revision_id, revision_sha256 = reviewed_proposal()
    target = proposals.docs[proposal_id]["reviews"][1]
    target["reviewerId"] = (
        proposals.docs[proposal_id]["reviews"][0]["reviewerId"]
        if collapse == "reused_reviewer"
        else AUTHOR.address.lower()
    )
    target["decisionSha256"] = content_sha256(
        {key: value for key, value in target.items() if key != "decisionSha256"}
    )
    with pytest.raises(StudyActivationError, match="study_not_permit_candidate"):
        challenge_for(service(proposals), proposal_id, revision_id, revision_sha256)


@pytest.mark.parametrize(
    "path,value",
    [
        (("release", "releaseSha256"), "f" * 64),
        (("activationProfile", "content", "algorithmImageDigest"), "sha256:" + "f" * 64),
        (("activationProfile", "content", "referenceSha256"), "f" * 64),
        (("activationProfile", "content", "operationalPolicySha256"), "f" * 64),
        (("activationProfile", "content", "environment"), "other-generated"),
        (("activationProfile", "content", "limits", "maximumParticipants"), 99),
        (("decisions", 0, "decisionSha256"), "f" * 64),
    ],
)
def test_any_stored_activation_bundle_mutation_fails_closed(path, value):
    proposals, proposal_id, revision_id, revision_sha256 = reviewed_proposal()
    activations = ActivationDao()
    current = service(proposals, activations)
    challenge = challenge_for(current, proposal_id, revision_id, revision_sha256)
    stored = activations.docs[proposal_id]["challenges"][challenge["challengeId"]]
    target = stored["bundle"]
    for segment in path[:-1]:
        target = target[segment]
    target[path[-1]] = value

    with pytest.raises(StudyActivationError, match="study_activation_bundle_stale"):
        current.apply(
            proposal_id,
            OPERATOR.address,
            ORIGIN,
            challenge["challengeId"],
            sign(OPERATOR, challenge["message"]),
        )


def test_challenge_message_mutation_cannot_authorize_the_unchanged_bundle():
    proposals, proposal_id, revision_id, revision_sha256 = reviewed_proposal()
    activations = ActivationDao()
    current = service(proposals, activations)
    challenge = challenge_for(current, proposal_id, revision_id, revision_sha256)
    stored = activations.docs[proposal_id]["challenges"][challenge["challengeId"]]
    stored["message"] = "Sign an unrelated request"

    with pytest.raises(StudyActivationError, match="study_activation_bundle_stale"):
        current.apply(
            proposal_id,
            OPERATOR.address,
            ORIGIN,
            challenge["challengeId"],
            sign(OPERATOR, stored["message"]),
        )


def test_proposal_or_decision_change_after_challenge_invalidates_authority():
    proposals, proposal_id, revision_id, revision_sha256 = reviewed_proposal()
    current = service(proposals)
    challenge = challenge_for(current, proposal_id, revision_id, revision_sha256)
    proposals.docs[proposal_id]["revisions"][-1]["title"] = "Changed after review"
    with pytest.raises(StudyProposalConflict, match="commitment is invalid"):
        current.apply(
            proposal_id,
            OPERATOR.address,
            ORIGIN,
            challenge["challengeId"],
            sign(OPERATOR, challenge["message"]),
        )

    proposals, proposal_id, revision_id, revision_sha256 = reviewed_proposal()
    current = service(proposals)
    challenge = challenge_for(current, proposal_id, revision_id, revision_sha256)
    decision = proposals.docs[proposal_id]["reviews"][0]
    decision["evidenceSha256"] = "f" * 64
    decision["decisionSha256"] = content_sha256(
        {key: value for key, value in decision.items() if key != "decisionSha256"}
    )
    with pytest.raises(StudyActivationError, match="study_activation_bundle_stale"):
        current.apply(
            proposal_id,
            OPERATOR.address,
            ORIGIN,
            challenge["challengeId"],
            sign(OPERATOR, challenge["message"]),
        )


def test_wrong_operator_origin_signature_expiry_and_replay_fail_closed():
    proposals, proposal_id, revision_id, revision_sha256 = reviewed_proposal()
    clock = Clock()
    current = service(proposals, clock=clock)
    with pytest.raises(StudyActivationError, match="study_operator_forbidden"):
        current.create_challenge(
            proposal_id, WRONG.address, ORIGIN, revision_id, revision_sha256
        )
    with pytest.raises(StudyActivationError, match="origin_forbidden"):
        current.create_challenge(
            proposal_id,
            OPERATOR.address,
            "https://wrong.example",
            revision_id,
            revision_sha256,
        )
    with pytest.raises(StudyProposalConflict, match="changed concurrently"):
        challenge_for(current, proposal_id, revision_id, "0" * 64)

    challenge = challenge_for(current, proposal_id, revision_id, revision_sha256)
    with pytest.raises(StudyActivationError, match="signature_invalid"):
        current.apply(
            proposal_id,
            OPERATOR.address,
            ORIGIN,
            challenge["challengeId"],
            sign(WRONG, challenge["message"]),
        )
    signature = sign(OPERATOR, challenge["message"])
    current.apply(proposal_id, OPERATOR.address, ORIGIN, challenge["challengeId"], signature)
    with pytest.raises(StudyActivationError, match="challenge_used"):
        current.apply(
            proposal_id, OPERATOR.address, ORIGIN, challenge["challengeId"], signature
        )

    expired = challenge_for(current, proposal_id, revision_id, revision_sha256)
    clock.value += 301
    with pytest.raises(StudyActivationError, match="challenge_expired"):
        current.apply(
            proposal_id,
            OPERATOR.address,
            ORIGIN,
            expired["challengeId"],
            sign(OPERATOR, expired["message"]),
        )


def test_concurrent_application_creates_exactly_one_immutable_permit():
    proposals, proposal_id, revision_id, revision_sha256 = reviewed_proposal()
    current = service(proposals)
    challenge = challenge_for(current, proposal_id, revision_id, revision_sha256)
    signature = sign(OPERATOR, challenge["message"])
    outcomes = []
    barrier = threading.Barrier(2)

    def apply():
        barrier.wait()
        try:
            outcomes.append(
                current.apply(
                    proposal_id,
                    OPERATOR.address,
                    ORIGIN,
                    challenge["challengeId"],
                    signature,
                )["status"]
            )
        except StudyActivationError as error:
            outcomes.append(error.message)

    threads = [threading.Thread(target=apply) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert outcomes.count("permitted") == 1
    assert len(outcomes) == 2
    assert any("already used" in outcome or "challenge_used" in outcome for outcome in outcomes)
