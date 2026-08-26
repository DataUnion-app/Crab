from copy import deepcopy

import pytest

from dao.study_activation_dao import (
    StudyActivationDao,
    StudyActivationStateError,
)


PROPOSAL_ID = "study_1"
CHALLENGE_ID = "1" * 32
BUNDLE_SHA256 = "a" * 64


@pytest.fixture
def dao(monkeypatch):
    current = StudyActivationDao()
    documents = {}

    def get_if_exists(doc_id):
        document = documents.get(doc_id)
        return document is not None, deepcopy(document)

    def save(doc_id, value):
        if doc_id in documents:
            raise RuntimeError("duplicate")
        documents[doc_id] = deepcopy(value)

    def mutate_doc(doc_id, mutator):
        documents[doc_id] = deepcopy(mutator(deepcopy(documents[doc_id])))

    monkeypatch.setattr(current, "get_if_exists", get_if_exists)
    monkeypatch.setattr(current, "save", save)
    monkeypatch.setattr(current, "mutate_doc", mutate_doc)
    return current, documents


def challenge():
    return {
        "challenge_id": CHALLENGE_ID,
        "bundle_sha256": BUNDLE_SHA256,
        "issued_at": 100,
        "expires_at": 200,
        "consumed_at": None,
    }


def permit():
    return {"permitId": "permit_" + "2" * 32, "status": "permitted"}


def test_permit_creation_and_challenge_consumption_share_one_cas_mutation(dao):
    current, documents = dao
    current.create_challenge(PROPOSAL_ID, challenge(), 100)
    stored = current.consume_challenge_and_create_permit(
        PROPOSAL_ID,
        CHALLENGE_ID,
        BUNDLE_SHA256,
        permit(),
        "0x" + "3" * 130,
        101,
    )

    document = documents[current._doc_id(PROPOSAL_ID)]
    assert stored == permit()
    assert document["challenges"][CHALLENGE_ID]["consumed_at"] == 101
    assert document["challenges"][CHALLENGE_ID]["permit_id"] == permit()["permitId"]
    assert document["permits"] == {permit()["permitId"]: permit()}
    assert len(document["challenges"][CHALLENGE_ID]["signature_sha256"]) == 64
    assert document["challenges"][CHALLENGE_ID]["signature"] == "0x" + "3" * 130

    with pytest.raises(StudyActivationStateError, match="already used"):
        current.consume_challenge_and_create_permit(
            PROPOSAL_ID,
            CHALLENGE_ID,
            BUNDLE_SHA256,
            {"permitId": "permit_" + "4" * 32},
            "0x" + "5" * 130,
            102,
        )


@pytest.mark.parametrize(
    "now,bundle,error",
    [
        (200, BUNDLE_SHA256, "expired"),
        (101, "b" * 64, "bundle changed"),
    ],
)
def test_expired_or_mismatched_challenge_cannot_create_a_permit(
    dao, now, bundle, error
):
    current, documents = dao
    current.create_challenge(PROPOSAL_ID, challenge(), 100)
    with pytest.raises(StudyActivationStateError, match=error):
        current.consume_challenge_and_create_permit(
            PROPOSAL_ID,
            CHALLENGE_ID,
            bundle,
            permit(),
            "0x" + "3" * 130,
            now,
        )
    assert documents[current._doc_id(PROPOSAL_ID)]["permits"] == {}
