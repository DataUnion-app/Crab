from copy import deepcopy
import hashlib
import json

from eth_account import Account
from eth_account.messages import encode_defunct
import pytest

from commands.dataunions.brainstem.value_commit import (
    BrainstemValueService,
    COMMITMENT_SCHEMA,
    RECEIPT_SCHEMA,
    RESULT_SCHEMA,
    ValueCommitError,
    canonical_json,
)
from dao.base_dao import DBResultError


JOB_ID = "a" * 64
JOB_ID_HASH = hashlib.sha256(JOB_ID.encode("utf-8")).hexdigest()
RELEASE_ID = "b" * 64
INPUT_SHA256 = "c" * 64
RESULT_SHA256 = "d" * 64
ALGORITHM_DIGEST = "sha256:" + "e" * 64
CONSENT_VERSION = "brainstem-tos-2026-07"
NODE_KEY = "0x" + "11" * 32
CRAB_KEY = "0x" + "22" * 32


class FakeStore:
    def __init__(self, documents=None):
        self.documents = deepcopy(documents or {})
        self.fail_once_for = None
        self.fail_mutate_once_for = None

    def get_if_exists(self, doc_id):
        document = self.documents.get(doc_id)
        return (document is not None, deepcopy(document))

    def get_doc_by_id(self, doc_id):
        if doc_id not in self.documents:
            raise KeyError(doc_id)
        return deepcopy(self.documents[doc_id])

    def save(self, doc_id, document):
        if self.fail_once_for == doc_id:
            self.fail_once_for = None
            raise DBResultError("generated", "injected failure")
        if doc_id in self.documents:
            raise DBResultError("generated", "conflict")
        self.documents[doc_id] = {"_id": doc_id, **deepcopy(document)}

    def mutate_doc(self, doc_id, mutator):
        if self.fail_mutate_once_for == doc_id:
            self.fail_mutate_once_for = None
            raise DBResultError("generated", "injected mutation failure")
        current = deepcopy(self.documents[doc_id])
        updated = mutator(current)
        if updated is not None:
            self.documents[doc_id] = updated
        return deepcopy(self.documents[doc_id])

    def committed_brainstem_value_entitlement_ids(self, documents):
        committed = set()
        for document in documents:
            commit = self.documents.get(document.get("commit_id"))
            if commit and commit.get("status") == "committed":
                committed.update(commit.get("entitlement_ids", []))
        return committed


class FakeUsers:
    def __init__(self, users):
        self.users = {user["_id"]: deepcopy(user) for user in users}

    def get_doc_by_id(self, user_id):
        if user_id not in self.users:
            raise KeyError(user_id)
        return deepcopy(self.users[user_id])


class FakeRelease:
    def __init__(self, users):
        self.document = {
            "document_type": "brainstem_c2d_cohort_release",
            "release_id": RELEASE_ID,
            "data_union": "brainstem",
            "purpose": "brainstem.resting-rr/v1",
            "consent_version": CONSENT_VERSION,
            "status": "active",
            "roster_user_ids": sorted(user["_id"] for user in users),
            "created_at": "2026-07-25T00:00:00Z",
            "activated_at": "2026-07-25T00:01:00Z",
            "expires_at": "2099-07-25T00:00:00Z",
        }

    def get_doc_by_id(self, doc_id):
        if doc_id != f"brainstem-c2d-release:{RELEASE_ID}":
            raise KeyError(doc_id)
        return deepcopy(self.document)


def generated_state(count=2):
    users = []
    records = {}
    contributors = []
    canaries = []
    for index in range(count):
        internal_id = f"generated-user-{index}"
        wallet = "0x" + f"{index + 1:040x}"
        owner = f"generated-owner-{index}"
        record_id = f"generated-record-{index}"
        content_hash = hashlib.sha256(record_id.encode("utf-8")).hexdigest()
        users.append({
            "_id": internal_id,
            "public_address": wallet,
            "usage_flag": "ACCEPTED",
            "guidelines_acceptance_flag": "ACCEPTED",
        })
        records[record_id] = {
            "_id": record_id,
            "file_type": "record",
            "created_by": owner,
            "content_hash": content_hash,
        }
        contributors.append({
            "internal_user_id": internal_id,
            "public_address": wallet,
            "record_owner": owner,
            "records": [{"id": record_id, "content_sha256": content_hash}],
        })
        canaries.extend([internal_id, wallet, owner, record_id])
    return users, records, contributors, canaries


def service(count=2):
    users, records, contributors, canaries = generated_state(count)
    rewards = FakeStore()
    metadata = FakeStore(records)
    user_store = FakeUsers(users)
    release = FakeRelease(users)
    value_service = BrainstemValueService(
        rewards_dao=rewards,
        metadata_dao=metadata,
        users_dao=user_store,
        release_dao=release,
        consent_version=CONSENT_VERSION,
        amount=3,
        approved_algorithm_digest=ALGORITHM_DIGEST,
        expected_node_signer=Account.from_key(NODE_KEY).address,
        signing_private_key=CRAB_KEY,
    )
    value_service.record_export(
        JOB_ID,
        RELEASE_ID,
        INPUT_SHA256,
        "brainstem.private-rr-cohort/v1",
        "brainstem.resting-rr/v1",
        contributors,
    )
    return value_service, rewards, metadata, user_store, canaries


def signed_receipt(**changes):
    receipt = {
        "schema": RECEIPT_SCHEMA,
        "jobIdHash": JOB_ID_HASH,
        "inputSha256": INPUT_SHA256,
        "resultSha256": RESULT_SHA256,
        "resultSchema": RESULT_SCHEMA,
        "resultStatus": "complete",
        "algorithmImageDigest": ALGORITHM_DIGEST,
        "completedAt": "2026-07-25T00:02:00Z",
        **changes,
    }
    signature = Account.from_key(NODE_KEY).sign_message(
        encode_defunct(primitive=canonical_json(receipt))
    ).signature.hex()
    return receipt, signature if signature.startswith("0x") else f"0x{signature}"


def test_signed_commit_is_private_equal_and_idempotent():
    value_service, rewards, _metadata, _users, canaries = service()
    receipt, signature = signed_receipt()

    first = value_service.commit(receipt, signature)
    repeated = value_service.commit(receipt, signature)

    assert first == repeated
    assert first["schema"] == COMMITMENT_SCHEMA
    assert first["participantCount"] == 2
    assert first["amountPerParticipant"] == 3
    unsigned = {key: value for key, value in first.items() if key != "signature"}
    assert Account.recover_message(
        encode_defunct(primitive=canonical_json(unsigned)),
        signature=first["signature"],
    ) == Account.from_key(CRAB_KEY).address
    entitlements = [
        document
        for document in rewards.documents.values()
        if document.get("document_type") == "brainstem_value_entitlement"
    ]
    assert len(entitlements) == 2
    assert {document["amount"] for document in entitlements} == {3}
    assert len({
        document["commit_id"] for document in entitlements
    }) == 1
    public_text = json.dumps(first)
    assert all(canary not in public_text for canary in canaries)


def test_second_job_reuses_release_entitlements_without_paying_twice():
    value_service, rewards, _metadata, _users, _canaries = service()
    first_receipt, first_signature = signed_receipt()
    first = value_service.commit(first_receipt, first_signature)
    first_manifest = rewards.documents[value_service.manifest_id(JOB_ID_HASH)]
    first_entitlements = {
        key: deepcopy(document)
        for key, document in rewards.documents.items()
        if document.get("document_type") == "brainstem_value_entitlement"
    }

    second_job_id = "f" * 64
    second_job_hash = hashlib.sha256(second_job_id.encode("utf-8")).hexdigest()
    second_input_sha256 = "1" * 64
    value_service.record_export(
        second_job_id,
        RELEASE_ID,
        second_input_sha256,
        "brainstem.private-rr-cohort/v1",
        "brainstem.resting-rr/v1",
        first_manifest["contributors"],
    )
    second_receipt, second_signature = signed_receipt(
        jobIdHash=second_job_hash,
        inputSha256=second_input_sha256,
        resultSha256="2" * 64,
        completedAt="2026-07-25T00:03:00Z",
    )

    second = value_service.commit(second_receipt, second_signature)

    assert second["participantCount"] == first["participantCount"] == 2
    assert {
        key: document
        for key, document in rewards.documents.items()
        if document.get("document_type") == "brainstem_value_entitlement"
    } == first_entitlements
    assert len([
        document
        for document in rewards.documents.values()
        if document.get("document_type") == "brainstem_value_commit"
    ]) == 2


def test_second_job_still_rechecks_consent_before_reusing_entitlements():
    value_service, rewards, _metadata, users, _canaries = service()
    first_receipt, first_signature = signed_receipt()
    value_service.commit(first_receipt, first_signature)
    first_manifest = rewards.documents[value_service.manifest_id(JOB_ID_HASH)]

    second_job_id = "f" * 64
    second_job_hash = hashlib.sha256(second_job_id.encode("utf-8")).hexdigest()
    second_input_sha256 = "1" * 64
    value_service.record_export(
        second_job_id,
        RELEASE_ID,
        second_input_sha256,
        "brainstem.private-rr-cohort/v1",
        "brainstem.resting-rr/v1",
        first_manifest["contributors"],
    )
    users.users["generated-user-0"]["usage_flag"] = "REJECTED"
    second_receipt, second_signature = signed_receipt(
        jobIdHash=second_job_hash,
        inputSha256=second_input_sha256,
        resultSha256="2" * 64,
        completedAt="2026-07-25T00:03:00Z",
    )

    with pytest.raises(
        ValueCommitError, match="contribution_no_longer_eligible"
    ):
        value_service.commit(second_receipt, second_signature)


def test_export_manifest_retry_must_match_exactly():
    value_service, rewards, _metadata, _users, _canaries = service()
    manifest_id = value_service.manifest_id(JOB_ID_HASH)
    manifest_count = len(rewards.documents)
    contributors = deepcopy(rewards.documents[manifest_id]["contributors"])

    assert value_service.record_export(
        JOB_ID,
        RELEASE_ID,
        INPUT_SHA256,
        "brainstem.private-rr-cohort/v1",
        "brainstem.resting-rr/v1",
        contributors,
    ) == manifest_id
    assert len(rewards.documents) == manifest_count

    contributors[0]["records"][0]["content_sha256"] = "f" * 64
    with pytest.raises(ValueCommitError, match="value_state_conflict"):
        value_service.record_export(
            JOB_ID,
            RELEASE_ID,
            INPUT_SHA256,
            "brainstem.private-rr-cohort/v1",
            "brainstem.resting-rr/v1",
            contributors,
        )


def test_partial_entitlement_write_retries_without_duplicates():
    value_service, rewards, _metadata, users, _canaries = service()
    receipt, signature = signed_receipt()
    manifest = rewards.documents[value_service.manifest_id(JOB_ID_HASH)]
    second_id = value_service._entitlement_id(
        manifest, manifest["contributors"][1]["internal_user_id"]
    )
    rewards.fail_once_for = second_id

    with pytest.raises(DBResultError, match="injected failure"):
        value_service.commit(receipt, signature)
    users.users["generated-user-0"]["usage_flag"] = "REJECTED"
    commitment = value_service.commit(receipt, signature)

    assert commitment["participantCount"] == 2
    assert len([
        document
        for document in rewards.documents.values()
        if document.get("document_type") == "brainstem_value_entitlement"
    ]) == 2
    assert len([
        document
        for document in rewards.documents.values()
        if document.get("document_type") == "brainstem_value_commit"
    ]) == 1


def test_retry_finishes_existing_commit_without_rechecking_withdrawn_contributor():
    value_service, rewards, _metadata, users, _canaries = service()
    receipt, signature = signed_receipt()
    manifest_id = value_service.manifest_id(JOB_ID_HASH)
    rewards.fail_mutate_once_for = manifest_id

    with pytest.raises(DBResultError, match="injected mutation failure"):
        value_service.commit(receipt, signature)
    users.users["generated-user-0"]["usage_flag"] = "REJECTED"

    commitment = value_service.commit(receipt, signature)

    assert commitment["participantCount"] == 2
    assert rewards.documents[manifest_id]["status"] == "committed"


@pytest.mark.parametrize("change", ["withdrawal", "deletion", "release"])
def test_change_before_commit_rejects_the_whole_value_set(change):
    value_service, rewards, metadata, users, _canaries = service()
    if change == "withdrawal":
        users.users["generated-user-0"]["usage_flag"] = "REJECTED"
    elif change == "deletion":
        del metadata.documents["generated-record-0"]
    else:
        value_service.release_dao.document["status"] = "revoked"
    receipt, signature = signed_receipt()

    with pytest.raises(ValueCommitError, match="contribution_no_longer_eligible"):
        value_service.commit(receipt, signature)

    assert not any(
        document.get("document_type") == "brainstem_value_commit"
        for document in rewards.documents.values()
    )


def test_result_status_does_not_change_equal_value():
    complete_service, _complete_rewards, _m1, _u1, _c1 = service()
    complete_receipt, complete_signature = signed_receipt()
    complete = complete_service.commit(complete_receipt, complete_signature)

    private_service, _private_rewards, _m2, _u2, _c2 = service()
    private_receipt, private_signature = signed_receipt(
        resultStatus="insufficient_data",
        resultSha256="f" * 64,
    )
    private = private_service.commit(private_receipt, private_signature)

    assert complete["amountPerParticipant"] == private["amountPerParticipant"] == 3
    assert complete["participantCount"] == 2
    assert private["participantCount"] is None


def test_tampered_or_wrong_signer_receipt_fails_closed():
    value_service, rewards, _metadata, _users, _canaries = service()
    receipt, signature = signed_receipt()
    receipt["resultSha256"] = "f" * 64
    with pytest.raises(ValueCommitError, match="compute_receipt_signature_invalid"):
        value_service.commit(receipt, signature)

    receipt, _signature = signed_receipt()
    wrong_signature = Account.from_key("0x" + "33" * 32).sign_message(
        encode_defunct(primitive=canonical_json(receipt))
    ).signature.hex()
    if not wrong_signature.startswith("0x"):
        wrong_signature = f"0x{wrong_signature}"
    with pytest.raises(ValueCommitError, match="compute_receipt_signature_invalid"):
        value_service.commit(receipt, wrong_signature)

    assert not any(
        document.get("document_type") == "brainstem_value_entitlement"
        for document in rewards.documents.values()
    )
