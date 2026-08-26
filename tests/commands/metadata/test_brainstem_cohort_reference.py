from copy import deepcopy
from datetime import datetime, timezone

import pytest

from commands.dataunions.brainstem.cohort_reference import (
    CohortReferenceError,
    CohortReferenceService,
)


NOW = datetime(2026, 7, 29, 12, 0, tzinfo=timezone.utc)
ANALYSIS = "brainstem.resting-hrv-methods/v1"
RELEASE = "a" * 64


class FakeDao:
    def __init__(self):
        self.documents = {}

    def get_doc_by_id(self, doc_id):
        if doc_id not in self.documents:
            raise RuntimeError("not found")
        return deepcopy(self.documents[doc_id])

    def save(self, doc_id, document):
        if doc_id in self.documents:
            raise RuntimeError("conflict")
        self.documents[doc_id] = deepcopy(document)

    def mutate_doc(self, doc_id, mutator):
        if doc_id not in self.documents:
            raise RuntimeError("not found")
        self.documents[doc_id] = mutator(deepcopy(self.documents[doc_id]))
        return deepcopy(self.documents[doc_id])


class FakeReleaseService:
    def __init__(self):
        self.active = {RELEASE}

    def active_member_ids(self, release_id):
        if release_id not in self.active:
            raise RuntimeError("inactive")
        return {"private-member"}


def service():
    return CohortReferenceService(
        FakeDao(), FakeReleaseService(), now=lambda: NOW
    )


def draft(reference_id, *, supersedes=None, version="reviewed-v1"):
    return {
        "analysis_id": ANALYSIS,
        "reference_sha256": reference_id,
        "artifact_sha256": ("c" if reference_id[0] != "c" else "d") * 64,
        "version": version,
        "source_release_id": RELEASE,
        "algorithm_image_digest": "sha256:" + "e" * 64,
        "approved_manifest_sha256": "f" * 64,
        "supersedes": supersedes,
    }


def test_reference_versions_are_immutable_and_corrections_supersede():
    references = service()
    first_id = "1" * 64
    second_id = "2" * 64

    references.draft(**draft(first_id))
    references.activate(ANALYSIS, first_id, "science-privacy-security:review-1")
    references.draft(
        **draft(second_id, supersedes=first_id, version="reviewed-v2")
    )
    readiness = references.public_projection(ANALYSIS)
    assert set(readiness) == {"state", "revision", "evaluatedAt"}
    assert readiness["state"] == "refresh_available"
    assert readiness["revision"] == second_id

    references.activate(ANALYSIS, second_id, "science-privacy-security:review-2")
    assert references.reference(ANALYSIS, first_id)["state"] == "superseded"
    assert references.reference(ANALYSIS, second_id)["state"] == "active"
    assert references.is_usable(ANALYSIS, first_id) is False
    assert references.is_usable(ANALYSIS, second_id) is True
    assert references.public_projection(ANALYSIS)["state"] == "current"


def test_withdraw_then_delete_blocks_use_and_retains_only_tombstone_digest():
    references = service()
    reference_id = "3" * 64
    references.draft(**draft(reference_id))
    references.activate(ANALYSIS, reference_id, "review:approved")

    withdrawn = references.withdraw(ANALYSIS, reference_id, "privacy:withdraw")
    assert withdrawn["state"] == "withdrawn"
    assert references.public_projection(ANALYSIS)["state"] == "unavailable"
    assert references.is_usable(ANALYSIS, reference_id) is False

    deleted = references.delete(ANALYSIS, reference_id, "privacy:delete")
    assert deleted["state"] == "deleted"
    assert deleted["artifact_sha256"] == "c" * 64
    assert reference_id in str(deleted)
    assert "privacy:delete" not in str(deleted)


def test_bound_state_checks_release_and_exact_runtime_pins():
    references = service()
    reference_id = "7" * 64
    references.draft(**draft(reference_id))
    references.activate(ANALYSIS, reference_id, "review:approved")

    assert references.bound_state(
        ANALYSIS,
        reference_id,
        algorithm_image_digest="sha256:" + "e" * 64,
        approved_manifest_sha256="f" * 64,
    ) == "current"
    assert references.bound_state(
        ANALYSIS,
        reference_id,
        algorithm_image_digest="sha256:" + "9" * 64,
        approved_manifest_sha256="f" * 64,
    ) == "unavailable"

    references.release_service.active.clear()
    assert references.bound_state(ANALYSIS, reference_id) == "unavailable"
    assert references.public_projection(ANALYSIS) == {
        "state": "unavailable",
        "revision": reference_id,
        "evaluatedAt": "2026-07-29T00:00:00Z",
    }


def test_reference_draft_is_idempotent_but_contract_drift_fails():
    references = service()
    reference_id = "4" * 64
    contract = draft(reference_id)
    assert references.draft(**contract) == references.draft(**contract)
    with pytest.raises(CohortReferenceError, match="reference_conflict"):
        references.draft(**{**contract, "version": "changed"})


def test_active_reference_cannot_be_deleted_or_replaced_without_binding():
    references = service()
    first_id = "5" * 64
    second_id = "6" * 64
    references.draft(**draft(first_id))
    references.activate(ANALYSIS, first_id, "review:approved")

    with pytest.raises(CohortReferenceError, match="reference_not_deletable"):
        references.delete(ANALYSIS, first_id, "privacy:delete")
    with pytest.raises(CohortReferenceError, match="reference_predecessor_invalid"):
        references.draft(**draft(second_id))


def test_first_reference_cannot_claim_an_unknown_predecessor():
    references = service()

    with pytest.raises(CohortReferenceError, match="reference_predecessor_invalid"):
        references.draft(**draft("8" * 64, supersedes="9" * 64))
