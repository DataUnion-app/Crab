from copy import deepcopy
import threading

from eth_account import Account
from eth_account.messages import encode_defunct
import pytest

from commands.dataunions.brainstem.study_data_authorization import (
    StudyDataAuthorizationError,
    StudyDataAuthorizationService,
)
from commands.users.participant_auth import rfc3339
from dao.study_activation_dao import StudyActivationDao


NOW = 1785595200
PROPOSAL_ID = "study_" + "a" * 32
ACTIVATION_PERMIT_ID = "permit_" + "b" * 32
OPERATOR = Account.from_key("0x" + "31" * 32)
ORIGIN = "https://desci.example"
MANIFEST = "1" * 64
RELEASE = "2" * 64
COHORT = "3" * 64
IMAGE = "sha256:" + "4" * 64


class Clock:
    def __init__(self):
        self.value = NOW

    def __call__(self):
        return self.value


class Activation:
    def __init__(self):
        self.permit = {
            "permitId": ACTIVATION_PERMIT_ID,
            "permitSha256": "5" * 64,
            "operatorId": OPERATOR.address.lower(),
            "proposalId": PROPOSAL_ID,
            "revisionId": "revision_" + "6" * 32,
            "revisionSha256": "7" * 64,
            "expiresAt": rfc3339(NOW + 3600),
            "bundle": {
                "decisions": [
                    {"domain": domain, "decisionSha256": str(index) * 64}
                    for index, domain in enumerate(
                        ("scientific", "privacy", "security", "ethics"), 6
                    )
                ],
                "release": {
                    "offeringId": "brainstem.apdet-retrospective-study",
                    "releaseVersion": "1.0.0",
                    "releaseSha256": RELEASE,
                },
                "activationProfile": {
                    "content": {"algorithmImageDigest": IMAGE}
                },
            },
        }

    def load_verified_permit(self, proposal_id, permit_id):
        assert proposal_id == PROPOSAL_ID
        assert permit_id == ACTIVATION_PERMIT_ID
        return deepcopy(self.permit)


@pytest.fixture
def setup(monkeypatch):
    dao = StudyActivationDao()
    documents = {
        dao._doc_id(PROPOSAL_ID): {
            "document_type": "brainstem_study_activation",
            "proposal_id": PROPOSAL_ID,
            "challenges": {},
            "permits": {},
        }
    }
    lock = threading.Lock()

    def get_if_exists(doc_id):
        with lock:
            value = documents.get(doc_id)
            return value is not None, deepcopy(value)

    def mutate_doc(doc_id, mutator):
        with lock:
            updated = mutator(deepcopy(documents[doc_id]))
            if updated is not None:
                documents[doc_id] = deepcopy(updated)

    monkeypatch.setattr(dao, "get_if_exists", get_if_exists)
    monkeypatch.setattr(dao, "mutate_doc", mutate_doc)
    clock = Clock()
    activation = Activation()
    ids = iter(format(index, "032x") for index in range(1, 20))
    service = StudyDataAuthorizationService(
        dao,
        activation,
        allowed_operators=[OPERATOR.address],
        allowed_origins=[ORIGIN],
        manifest_sha256=MANIFEST,
        cohort_release_id=COHORT,
        release_sha256=RELEASE,
        algorithm_image_digest=IMAGE,
        clock=clock,
        nonce_factory=lambda: "n" * 32,
        id_factory=lambda: next(ids),
    )
    return service, activation, clock


def signed_permit(service, action="eligibility", eligibility_receipt=None):
    challenge = service.create_challenge(
        action,
        PROPOSAL_ID,
        ACTIVATION_PERMIT_ID,
        OPERATOR.address,
        ORIGIN,
        eligibility_receipt,
    )
    signature = Account.sign_message(
        encode_defunct(text=challenge["message"]), OPERATOR.key
    ).signature.hex()
    return service.apply(
        PROPOSAL_ID,
        OPERATOR.address,
        ORIGIN,
        challenge["challengeId"],
        signature,
    )


def completed_eligibility(service):
    permit = signed_permit(service)
    result, receipt = service.execute(
        PROPOSAL_ID,
        permit["permitId"],
        "eligibility",
        "eligibility-run-1",
        lambda _binding: {"eligibleBand": "20_49"},
    )
    assert result == {"eligibleBand": "20_49"}
    return receipt


def test_separate_eligibility_and_compute_permits_are_single_use(setup):
    service, _activation, _clock = setup
    eligibility = completed_eligibility(service)
    compute = signed_permit(service, "compute", eligibility["receiptSha256"])
    artifact, receipt = service.execute(
        PROPOSAL_ID,
        compute["permitId"],
        "compute",
        "a" * 64,
        lambda _binding: b"aggregate-only",
    )
    assert artifact == b"aggregate-only"
    assert receipt["action"] == "compute"
    with pytest.raises(StudyDataAuthorizationError, match="already used"):
        service.execute(
            PROPOSAL_ID,
            compute["permitId"],
            "compute",
            "b" * 64,
            lambda _binding: b"never",
        )


def test_expired_wrong_action_and_unrelated_eligibility_fail_closed(setup):
    service, _activation, clock = setup
    permit = signed_permit(service)
    with pytest.raises(StudyDataAuthorizationError):
        service.execute(
            PROPOSAL_ID,
            permit["permitId"],
            "compute",
            "x",
            lambda _binding: b"x",
        )
    clock.value += 301
    with pytest.raises(StudyDataAuthorizationError, match="expired"):
        service.execute(
            PROPOSAL_ID,
            permit["permitId"],
            "eligibility",
            "x",
            lambda _binding: {},
        )
    with pytest.raises(StudyDataAuthorizationError, match="eligibility"):
        service.create_challenge(
            "compute",
            PROPOSAL_ID,
            ACTIVATION_PERMIT_ID,
            OPERATOR.address,
            ORIGIN,
            "f" * 64,
        )


@pytest.mark.parametrize("changed", ["manifest", "revision", "review", "release", "image"])
def test_challenge_rejects_every_stale_review_binding(setup, changed):
    service, activation, _clock = setup
    challenge = service.create_challenge(
        "eligibility",
        PROPOSAL_ID,
        ACTIVATION_PERMIT_ID,
        OPERATOR.address,
        ORIGIN,
    )
    signature = Account.sign_message(
        encode_defunct(text=challenge["message"]), OPERATOR.key
    ).signature.hex()
    if changed == "manifest":
        service.manifest_sha256 = "9" * 64
    elif changed == "revision":
        activation.permit["revisionSha256"] = "9" * 64
    elif changed == "review":
        activation.permit["bundle"]["decisions"][0]["decisionSha256"] = "9" * 64
    elif changed == "release":
        activation.permit["bundle"]["release"]["releaseSha256"] = "9" * 64
        service.release_sha256 = "9" * 64
    else:
        activation.permit["bundle"]["activationProfile"]["content"][
            "algorithmImageDigest"
        ] = "sha256:" + "9" * 64
        service.algorithm_image_digest = "sha256:" + "9" * 64
    with pytest.raises(StudyDataAuthorizationError, match="stale"):
        service.apply(
            PROPOSAL_ID,
            OPERATOR.address,
            ORIGIN,
            challenge["challengeId"],
            signature,
        )


def test_concurrent_execution_has_one_winner(setup):
    service, _activation, _clock = setup
    permit = signed_permit(service)
    barrier = threading.Barrier(2)
    outcomes = []

    def run(suffix):
        barrier.wait()
        try:
            service.execute(
                PROPOSAL_ID,
                permit["permitId"],
                "eligibility",
                suffix,
                lambda _binding: {"eligibleBand": "20_49"},
            )
            outcomes.append("accepted")
        except StudyDataAuthorizationError:
            outcomes.append("rejected")

    threads = [threading.Thread(target=run, args=(value,)) for value in ("a", "b")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sorted(outcomes) == ["accepted", "rejected"]


def test_malformed_stored_challenge_fails_closed(setup, monkeypatch):
    service, _activation, _clock = setup
    permit = signed_permit(service)
    original = service.dao.get_data_permit_evidence

    def malformed(*args):
        evidence = original(*args)
        evidence["challenge"].pop("origin")
        return evidence

    monkeypatch.setattr(service.dao, "get_data_permit_evidence", malformed)
    with pytest.raises(StudyDataAuthorizationError, match="study_data_permit_invalid"):
        service.execute(
            PROPOSAL_ID,
            permit["permitId"],
            "eligibility",
            "x",
            lambda _binding: {},
        )
