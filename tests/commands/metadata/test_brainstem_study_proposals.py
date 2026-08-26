from copy import deepcopy

import pytest

from commands.dataunions.brainstem.study_proposals import (
    StudyProposalConflict,
    StudyProposalError,
    StudyProposalForbidden,
    StudyProposalWorkflow,
    proposal_role,
    reviewed_revision_binding,
)
from commands.dataunions.brainstem.study_registry import (
    DEFAULT_STUDY_REGISTRY,
    RECORDING_FEASIBILITY_ID,
)
from commands.dataunions.studies.registry import content_sha256


AUTHOR = "0x" + "1" * 40
OTHER = "0x" + "2" * 40
EDITOR = "0x" + "3" * 40
VIEWER = "0x" + "4" * 40
REVIEWER = "0x" + "a" * 40
REVIEWERS = ["0x" + value * 40 for value in ("a", "b", "c", "d")]


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


class Dao:
    def __init__(self):
        self.docs = {}

    def create(self, document):
        self.docs[document["proposalId"]] = deepcopy(document)

    def get(self, proposal_id):
        return deepcopy(self.docs[proposal_id])

    def mutate(self, proposal_id, mutator):
        self.docs[proposal_id] = deepcopy(mutator(deepcopy(self.docs[proposal_id])))
        return deepcopy(self.docs[proposal_id])

    def list_accessible(self, actor, page, per_page):
        rows = [
            item for item in self.docs.values() if proposal_role(item, actor) is not None
        ]
        return rows[page * per_page : (page + 1) * per_page], False

    def list_queue(self, page, per_page, status=None):
        rows = [
            item
            for item in self.docs.values()
            if item["status"] != "draft" and (status is None or item["status"] == status)
        ]
        return rows[page * per_page : (page + 1) * per_page], False


def ids():
    counter = 0

    def factory(prefix):
        nonlocal counter
        counter += 1
        return "{}_{}".format(prefix, format(counter, "x"))

    return factory


def workflow():
    return StudyProposalWorkflow(Dao(), clock=lambda: "2026-07-31T00:00:00Z", id_factory=ids())


def evidence(domain):
    return content_sha256({"domain": domain, "fixture": "generated-only"})


def test_draft_actor_isolation_bounded_fields_and_stale_revision_rejection():
    flow = workflow()
    created = flow.create(AUTHOR, payload())
    assert created["status"] == "draft"
    with pytest.raises(StudyProposalForbidden):
        flow.get(created["proposalId"], OTHER)
    with pytest.raises(StudyProposalError, match="Invalid study proposal fields"):
        flow.create(AUTHOR, {**payload(), "arbitraryQuery": "all participants"})
    with pytest.raises(StudyProposalConflict, match="changed concurrently"):
        flow.add_revision(
            created["proposalId"],
            AUTHOR,
            payload(title="Changed study title"),
            "stale",
            created["currentRevisionSha256"],
        )
    owned = flow.list_accessible(AUTHOR, 0, 20)["rows"][0]
    assert owned["schema"] == "brainstem.study-proposal/v2"
    assert owned["access"]["ownerId"] == AUTHOR
    assert owned["revisions"] == created["revisions"]
    assert owned["reviews"] == []
    assert owned["events"] == created["events"]


def test_owner_editor_viewer_and_revocation_are_proposal_scoped():
    flow = workflow()
    created = flow.create(AUTHOR, payload())
    proposal_id = created["proposalId"]
    editor = flow.set_collaborator(proposal_id, AUTHOR, EDITOR, "editor", 1)
    viewer = flow.set_collaborator(proposal_id, AUTHOR, VIEWER, "viewer", 2)
    assert editor["access"]["version"] == 2
    assert viewer["access"]["version"] == 3
    assert proposal_role(viewer, EDITOR) == "editor"
    assert proposal_role(viewer, VIEWER) == "viewer"
    assert len(flow.list_accessible(EDITOR, 0, 20)["rows"]) == 1
    assert len(flow.list_accessible(OTHER, 0, 20)["rows"]) == 0

    revised = flow.add_revision(
        proposal_id,
        EDITOR,
        payload(title="Editor-authored study version"),
        viewer["currentRevisionId"],
        viewer["currentRevisionSha256"],
    )
    assert revised["revisions"][-1]["authorId"] == EDITOR
    with pytest.raises(StudyProposalForbidden):
        flow.add_revision(
            proposal_id,
            VIEWER,
            payload(title="Viewer must not edit"),
            revised["currentRevisionId"],
            revised["currentRevisionSha256"],
        )
    with pytest.raises(StudyProposalForbidden):
        flow.set_collaborator(proposal_id, EDITOR, OTHER, "viewer", 3)

    revoked = flow.set_collaborator(proposal_id, AUTHOR, EDITOR, None, 3)
    assert revoked["access"]["version"] == 4
    with pytest.raises(StudyProposalForbidden):
        flow.get(proposal_id, EDITOR)


def test_legacy_owner_binding_preserves_revision_commitments():
    flow = workflow()
    created = flow.create(AUTHOR, payload())
    proposal_id = created["proposalId"]
    legacy = deepcopy(flow.dao.docs[proposal_id])
    legacy["schema"] = "brainstem.study-proposal/v1"
    legacy.pop("access")
    flow.dao.docs[proposal_id] = legacy
    revisions = deepcopy(legacy["revisions"])

    bound = flow.bind_legacy_owner(
        proposal_id,
        OTHER,
        AUTHOR,
        created["revisions"][-1]["offeringId"],
        created["currentRevisionId"],
        created["currentRevisionSha256"],
    )
    assert bound["schema"] == "brainstem.study-proposal/v2"
    assert bound["authorId"] == AUTHOR
    assert bound["access"]["ownerId"] == OTHER
    assert bound["revisions"] == revisions
    with pytest.raises(StudyProposalForbidden):
        flow.get(proposal_id, AUTHOR)
    assert flow.get(proposal_id, OTHER)["currentRevisionSha256"] == created[
        "currentRevisionSha256"
    ]


def test_all_review_domains_complete_review_but_cannot_activate_or_export():
    flow = workflow()
    created = flow.create(AUTHOR, payload())
    proposal_id = created["proposalId"]
    revision_id = created["currentRevisionId"]
    revision_sha256 = created["currentRevisionSha256"]
    submitted = flow.submit(proposal_id, AUTHOR, revision_id, revision_sha256)
    assert submitted["status"] == "submitted"

    current = submitted
    for domain, reviewer in zip(
        ("scientific", "privacy", "security", "ethics"), REVIEWERS
    ):
        current = flow.review(
            proposal_id,
            reviewer,
            domain,
            "approved",
            revision_id,
            revision_sha256,
            "Generated-only domain review completed for this exact revision.",
            evidence(domain),
        )
    assert current["status"] == "review_complete"
    binding = reviewed_revision_binding(
        flow.dao.get(proposal_id),
        proposal_id,
        revision_id,
        revision_sha256,
        created["revisions"][-1]["offeringId"],
        created["revisions"][-1]["releaseVersion"],
        created["revisions"][-1]["releaseSha256"],
    )
    assert binding["revisionSha256"] == revision_sha256
    assert {item["domain"] for item in binding["reviewDecisions"]} == {
        "scientific",
        "privacy",
        "security",
        "ethics",
    }
    with pytest.raises(StudyProposalConflict):
        reviewed_revision_binding(
            flow.dao.get(proposal_id),
            proposal_id,
            revision_id,
            revision_sha256,
            created["revisions"][-1]["offeringId"],
            created["revisions"][-1]["releaseVersion"],
            "f" * 64,
        )
    assert not hasattr(flow, "activate")
    assert not hasattr(flow, "export")
    assert "approved" not in {item["status"] for item in [created, submitted, current]}


def test_author_and_reused_reviewer_cannot_collapse_domain_independence():
    flow = workflow()
    created = flow.create(AUTHOR, payload())
    proposal_id = created["proposalId"]
    revision_id = created["currentRevisionId"]
    revision_sha256 = created["currentRevisionSha256"]
    flow.submit(proposal_id, AUTHOR, revision_id, revision_sha256)

    with pytest.raises(StudyProposalForbidden, match="cannot review"):
        flow.review(
            proposal_id,
            AUTHOR,
            "scientific",
            "approved",
            revision_id,
            revision_sha256,
            "An author must not approve their own submitted revision.",
            evidence("scientific"),
        )

    flow.review(
        proposal_id,
        REVIEWERS[0],
        "scientific",
        "approved",
        revision_id,
        revision_sha256,
        "The scientific checkpoint is bound to this exact revision.",
        evidence("scientific"),
    )
    with pytest.raises(StudyProposalConflict, match="different reviewer"):
        flow.review(
            proposal_id,
            REVIEWERS[0],
            "privacy",
            "approved",
            revision_id,
            revision_sha256,
            "A separate reviewer must own the privacy checkpoint.",
            evidence("privacy"),
        )


def test_changes_request_requires_new_revision_and_invalidates_prior_completion():
    flow = workflow()
    created = flow.create(AUTHOR, payload())
    proposal_id = created["proposalId"]
    revision_id = created["currentRevisionId"]
    revision_sha256 = created["currentRevisionSha256"]
    flow.submit(proposal_id, AUTHOR, revision_id, revision_sha256)
    changes = flow.review(
        proposal_id,
        REVIEWER,
        "privacy",
        "changes_requested",
        revision_id,
        revision_sha256,
        "Clarify the retention boundary before another review.",
        evidence("privacy"),
    )
    assert changes["status"] == "changes_requested"

    revised = flow.add_revision(
        proposal_id,
        AUTHOR,
        payload(retention="Retain generated evidence for exactly thirty generated days."),
        revision_id,
        revision_sha256,
    )
    assert revised["status"] == "draft"
    assert revised["currentRevisionId"] != revision_id
    assert all(
        review["revisionId"] != revised["currentRevisionId"]
        for review in revised["reviews"]
    )


def test_revision_and_decision_commitments_are_canonical_and_tamper_evident():
    flow = workflow()
    original = payload()
    reordered = {key: original[key] for key in reversed(list(original))}
    first = flow.create(AUTHOR, original)
    second = workflow().create(AUTHOR, reordered)
    assert first["currentRevisionSha256"] == second["currentRevisionSha256"]

    proposal_id = first["proposalId"]
    revision_id = first["currentRevisionId"]
    revision_sha256 = first["currentRevisionSha256"]
    flow.submit(proposal_id, AUTHOR, revision_id, revision_sha256)
    reviewed = flow.review(
        proposal_id,
        REVIEWER,
        "privacy",
        "approved",
        revision_id,
        revision_sha256,
        "The generated privacy evidence matches this exact revision.",
        evidence("privacy"),
    )
    decision = reviewed["reviews"][0]
    assert len(decision["decisionSha256"]) == 64
    assert decision["revisionSha256"] == revision_sha256

    for target, field, value in (
        ("revision", "title", "One changed byte"),
        ("revision", "releaseSha256", "f" * 64),
        ("revision", "createdAt", "2026-07-31T00:00:01Z"),
        ("review", "reviewerId", OTHER),
        ("review", "evidenceSha256", "e" * 64),
        ("review", "occurredAt", "2026-07-31T00:00:01Z"),
    ):
        document = deepcopy(flow.dao.docs[proposal_id])
        collection = (
            document["revisions"] if target == "revision" else document["reviews"]
        )
        collection[0][field] = value
        flow.dao.docs[proposal_id] = document
        with pytest.raises(StudyProposalConflict, match="commitment is invalid"):
            flow.get(proposal_id, AUTHOR)
        flow.dao.docs[proposal_id] = deepcopy(reviewed | {"_id": proposal_id})


def test_stale_revision_hash_and_added_committed_fields_cannot_be_reviewed():
    flow = workflow()
    created = flow.create(AUTHOR, payload())
    proposal_id = created["proposalId"]
    revision_id = created["currentRevisionId"]
    revision_sha256 = created["currentRevisionSha256"]
    flow.submit(proposal_id, AUTHOR, revision_id, revision_sha256)

    with pytest.raises(StudyProposalConflict, match="changed concurrently"):
        flow.review(
            proposal_id,
            REVIEWER,
            "privacy",
            "approved",
            revision_id,
            "0" * 64,
            "This must not attach to a stale commitment.",
            evidence("privacy"),
        )

    flow.dao.docs[proposal_id]["revisions"][0]["unexpected"] = True
    with pytest.raises(StudyProposalConflict, match="commitment is invalid"):
        flow.review(
            proposal_id,
            REVIEWER,
            "privacy",
            "approved",
            revision_id,
            revision_sha256,
            "Unknown committed fields must fail closed.",
            evidence("privacy"),
        )
