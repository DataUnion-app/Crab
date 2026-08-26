from types import SimpleNamespace

import pytest

from commands.dataunions.brainstem.c2d_export import C2DExportError
from commands.dataunions.brainstem.study_eligibility import StudyEligibilityPreview
from commands.dataunions.brainstem.study_data_authorization import (
    StudyDataAuthorizationError,
)
from commands.dataunions.brainstem.study_proposals import StudyProposalConflict


PROPOSAL_ID = "study_" + "a" * 32
REVISION_ID = "revision_" + "b" * 32
REVISION_SHA256 = "c" * 64
ACTOR = "0x" + "1" * 40


class Workflow:
    def __init__(self, status="review_complete"):
        self.status = status

    def get(self, proposal_id, actor, can_review=False):
        assert proposal_id == PROPOSAL_ID
        assert actor == ACTOR
        return {
            "status": self.status,
            "currentRevisionId": REVISION_ID,
            "currentRevisionSha256": REVISION_SHA256,
            "revisions": [
                {
                    "revisionId": REVISION_ID,
                    "offeringId": "brainstem.apdet-retrospective-study",
                    "releaseVersion": "1.0.0",
                    "releaseSha256": "b" * 64,
                }
            ],
        }


class Exporter:
    def __init__(self, count):
        self.count = count

    def select_full_night(self, release_id):
        assert release_id == "d" * 64
        if self.count is None:
            raise C2DExportError("source_unavailable", 503)
        return SimpleNamespace(
            stats={
                "participant_count": self.count,
                "consent_or_release_excluded_participant_count": 3,
                "no_qualifying_full_night_participant_count": 21,
                "ineligible_record_count": 0,
            }
        )


def preview(count, status="review_complete"):
    return StudyEligibilityPreview(
        Workflow(status),
        Exporter(count),
        "d" * 64,
        "brainstem.apdet-retrospective-study",
        "1.0.0",
        "b" * 64,
        generated_only=True,
        clock=lambda: "2026-08-05T00:00:00Z",
    )


def evaluate(service):
    return service.evaluate(
        PROPOSAL_ID, ACTOR, REVISION_ID, REVISION_SHA256
    )


def test_preview_requires_the_exact_reviewed_release():
    service = StudyEligibilityPreview(
        Workflow(),
        Exporter(20),
        "d" * 64,
        "brainstem.apdet-retrospective-study",
        "1.0.0",
        "f" * 64,
        generated_only=True,
        clock=lambda: "2026-08-05T00:00:00Z",
    )
    with pytest.raises(StudyProposalConflict):
        evaluate(service)


def test_preview_suppresses_exact_counts_below_the_floor():
    result = evaluate(preview(19))
    assert result["state"] == "under_disclosure_floor"
    assert result["eligibleBand"] == "under_disclosure_floor"
    assert result["exclusionBands"] == {
        "consentOrRelease": "under_disclosure_floor",
        "noQualifyingFullNight": "20_49",
        "qualityOrDuration": "none",
    }
    assert "19" not in str(result)


def test_preview_releases_only_bands_at_the_floor():
    result = evaluate(preview(20))
    assert result["state"] == "eligible"
    assert result["eligibleBand"] == "20_49"
    assert not any(
        key.lower().endswith("count") for key in result | result["exclusionBands"]
    )


def test_preview_requires_current_completed_review_and_fails_closed():
    with pytest.raises(StudyProposalConflict):
        evaluate(preview(20, status="reviewing"))
    result = evaluate(preview(None))
    assert result["state"] == "unavailable"
    assert "eligibleBand" not in result


def test_real_preview_requires_a_consumed_one_shot_authorization():
    service = StudyEligibilityPreview(
        Workflow(),
        Exporter(20),
        "d" * 64,
        "brainstem.apdet-retrospective-study",
        "1.0.0",
        "b" * 64,
        clock=lambda: "2026-08-05T00:00:00Z",
    )
    with pytest.raises(StudyDataAuthorizationError, match="authorization_required"):
        evaluate(service)
    result = service.evaluate(
        PROPOSAL_ID,
        ACTOR,
        REVISION_ID,
        REVISION_SHA256,
        authorized=True,
    )
    assert result["eligibleBand"] == "20_49"
