from copy import deepcopy

import pytest

from commands.dataunions.brainstem.algorithm_proposals import (
    AlgorithmProposalWorkflow,
    ProposalConflictError,
    ProposalForbiddenError,
    ProposalValidationError,
)
from tests.algorithm_proposal_helpers import (
    ADMIN,
    OTHER,
    SCIENTIST,
    InMemoryProposalDao,
    revision_payload,
)


@pytest.fixture
def workflow():
    counter = iter(range(1000))
    return AlgorithmProposalWorkflow(
        InMemoryProposalDao(),
        clock=lambda: "2026-07-22T00:00:00Z",
        id_factory=lambda prefix: "{}_{}".format(prefix, next(counter)),
    )


def submit(workflow, wallet=SCIENTIST, **changes):
    return workflow.create(wallet, revision_payload(**changes))


def review(workflow, proposal, event_type, **evidence):
    payload = {
        "type": event_type,
        "expected_revision_id": proposal["current_revision_id"],
    }
    payload.update(evidence)
    return workflow.append_admin_event(proposal["proposal_id"], ADMIN, payload)


def approval_evidence():
    return {
        "source_commit": "a" * 40,
        "source_sha256": "b" * 64,
        "reviewed_image_digest": "sha256:" + "c" * 64,
        "security_review_ref": "security-review-2026-07-22",
        "security_scan_report_ref": "artifact://security/scan-2026-07-22.sarif",
        "security_scan_report_sha256": "d" * 64,
        "security_scan_scanner": "docker-scout",
        "security_scan_scanner_version": "v1.23.1",
        "security_scan_policy": "brainstem.no-high-critical/v1",
        "security_scan_completed_at": "2026-07-22T00:00:00Z",
        "scientific_review_ref": "science-review-2026-07-22",
    }


def test_revision_and_review_events_are_immutable(workflow):
    proposal = submit(workflow)
    original_revision = deepcopy(proposal["revisions"][0])

    reviewing = review(workflow, proposal, "reviewing")
    changes = review(
        workflow,
        reviewing,
        "changes_requested",
        note="Document the small-cell suppression test.",
    )

    assert changes["revisions"][0] == original_revision
    assert [event["type"] for event in changes["events"]] == [
        "submitted",
        "reviewing",
        "changes_requested",
    ]
    assert changes["status"] == "changes_requested"


def test_requested_changes_create_a_linked_revision(workflow):
    proposal = submit(workflow)
    proposal = review(workflow, proposal, "reviewing")
    proposal = review(
        workflow,
        proposal,
        "changes_requested",
        note="Add the missing adversarial result tests.",
    )
    previous_revision = proposal["current_revision_id"]

    revised_payload = revision_payload(title="Resting R-R cohort summary v2")
    revised = workflow.add_revision(
        proposal["proposal_id"], SCIENTIST, revised_payload, previous_revision
    )

    assert revised["status"] == "submitted"
    assert revised["current_revision_number"] == 2
    assert revised["revisions"][1]["supersedes_revision_id"] == previous_revision
    assert revised["revisions"][0]["title"] == "Resting R-R cohort summary"


def test_approval_requires_immutable_source_and_review_evidence(workflow):
    proposal = review(workflow, submit(workflow), "reviewing")
    with pytest.raises(ProposalValidationError):
        review(workflow, proposal, "approved", note="Looks good.")

    approved = review(
        workflow,
        proposal,
        "approved",
        note="Disclosure controls and result contract passed review.",
        **approval_evidence()
    )

    assert approved["status"] == "approved"
    assert approved["events"][-1]["evidence"]["source_sha256"] == "b" * 64


def test_publishing_and_whitelisting_only_append_operator_evidence(workflow):
    proposal = review(workflow, submit(workflow), "reviewing")
    proposal = review(
        workflow,
        proposal,
        "approved",
        note="Approved after review.",
        **approval_evidence()
    )
    proposal = review(
        workflow,
        proposal,
        "published",
        image_digest="sha256:" + "c" * 64,
        algorithm_did="did:ope:" + "d" * 64,
        service_id="compute",
        chain_id=11155420,
        publication_tx_hash="0x" + "e" * 64,
    )
    proposal = review(
        workflow,
        proposal,
        "whitelisted",
        dataset_did="did:ope:" + "f" * 64,
        allowlist_tx_hash="0x" + "1" * 64,
    )

    assert proposal["status"] == "whitelisted"
    assert proposal["events"][-2]["evidence"]["chain_id"] == 11155420
    assert proposal["events"][-1]["evidence"]["dataset_did"].startswith("did:ope:")


@pytest.mark.parametrize(
    "field,value",
    [
        ("security_scan_report_sha256", "not-a-digest"),
        ("security_scan_scanner", "Docker Scout"),
        ("security_scan_scanner_version", "latest"),
        ("security_scan_policy", "allow-high/v1"),
        ("security_scan_completed_at", "2026-07-22"),
    ],
)
def test_approval_rejects_unbound_or_malformed_scan_evidence(workflow, field, value):
    proposal = review(workflow, submit(workflow), "reviewing")
    evidence = approval_evidence()
    evidence[field] = value

    with pytest.raises(ProposalValidationError):
        review(
            workflow,
            proposal,
            "approved",
            note="Invalid scan evidence must fail closed.",
            **evidence
        )


def test_publication_digest_must_match_scanned_approval(workflow):
    proposal = review(workflow, submit(workflow), "reviewing")
    proposal = review(
        workflow,
        proposal,
        "approved",
        note="Approved exact scanned image.",
        **approval_evidence()
    )

    with pytest.raises(ProposalConflictError):
        review(
            workflow,
            proposal,
            "published",
            image_digest="sha256:" + "9" * 64,
            algorithm_did="did:ope:" + "d" * 64,
            service_id="compute",
            chain_id=11155420,
            publication_tx_hash="0x" + "e" * 64,
        )


def test_invalid_or_stale_transitions_fail_closed(workflow):
    proposal = submit(workflow)
    with pytest.raises(ProposalConflictError):
        review(
            workflow,
            proposal,
            "approved",
            note="Skipped review.",
            **approval_evidence()
        )

    reviewing = review(workflow, proposal, "reviewing")
    stale_payload = {
        "type": "rejected",
        "expected_revision_id": "revision_stale",
        "note": "Stale review action.",
    }
    with pytest.raises(ProposalConflictError):
        workflow.append_admin_event(proposal["proposal_id"], ADMIN, stale_payload)
    assert reviewing["status"] == "reviewing"


def test_ownership_and_bounded_pagination(workflow):
    first = submit(workflow)
    submit(workflow)
    submit(workflow, wallet=OTHER)

    with pytest.raises(ProposalForbiddenError):
        workflow.get_for_actor(first["proposal_id"], OTHER)
    assert workflow.get_for_actor(first["proposal_id"], ADMIN, is_admin=True)

    page = workflow.list_for_submitter(SCIENTIST, page=0, per_page=1)
    assert len(page["rows"]) == 1
    assert page["has_more"] is True
    assert "revisions" not in page["rows"][0]


@pytest.mark.parametrize(
    "changes",
    [
        {"participant_wallet": SCIENTIST},
        {"source_url": "http://example.com/source"},
        {"source_url": "https://token@example.com/source"},
        {"source_url": "https://[invalid/source"},
        {"paper_url": "https://example.com/paper#credential"},
        {"title": "x" * 121},
        {"input_schema_version": "raw-participant-records/v1"},
    ],
)
def test_payload_allowlist_rejects_data_credentials_and_unbounded_fields(
    workflow, changes
):
    with pytest.raises(ProposalValidationError):
        submit(workflow, **changes)
