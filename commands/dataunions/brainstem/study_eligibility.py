from datetime import datetime, timezone

from commands.dataunions.brainstem.c2d_export import (
    C2DExportError,
    FULL_NIGHT_SELECTOR_VERSION,
)
from commands.dataunions.brainstem.limits import MINIMUM_DISCLOSURE_PARTICIPANTS
from commands.dataunions.brainstem.study_proposals import StudyProposalConflict
from commands.dataunions.brainstem.study_data_authorization import (
    StudyDataAuthorizationError,
)


SCHEMA = "brainstem.study-eligibility-preview/v1"
SELECTOR = FULL_NIGHT_SELECTOR_VERSION


def _band(count):
    if count == 0:
        return "none"
    if count < MINIMUM_DISCLOSURE_PARTICIPANTS:
        return "under_disclosure_floor"
    if count < 50:
        return "20_49"
    if count < 100:
        return "50_99"
    return "100_plus"


class StudyEligibilityPreview:
    def __init__(
        self,
        workflow,
        exporter,
        release_id,
        offering_id,
        release_version,
        release_sha256,
        generated_only=False,
        clock=None,
    ):
        self.workflow = workflow
        self.exporter = exporter
        self.release_id = release_id
        self.offering_id = offering_id
        self.release_version = release_version
        self.release_sha256 = release_sha256
        self.generated_only = generated_only
        self.clock = clock or (
            lambda: datetime.now(timezone.utc).isoformat(timespec="seconds")
        )

    def evaluate(
        self,
        proposal_id,
        actor,
        expected_revision_id,
        expected_revision_sha256,
        authorized=False,
    ):
        proposal = self.workflow.get(proposal_id, actor)
        revision = next(
            (
                item
                for item in proposal["revisions"]
                if item["revisionId"] == expected_revision_id
            ),
            None,
        )
        if (
            proposal.get("status") != "review_complete"
            or proposal.get("currentRevisionId") != expected_revision_id
            or proposal.get("currentRevisionSha256") != expected_revision_sha256
            or revision is None
            or revision.get("offeringId") != self.offering_id
            or revision.get("releaseVersion") != self.release_version
            or revision.get("releaseSha256") != self.release_sha256
        ):
            raise StudyProposalConflict("Study proposal release is not eligible")
        base = {
            "schema": SCHEMA,
            "proposalId": proposal_id,
            "revisionId": expected_revision_id,
            "revisionSha256": expected_revision_sha256,
            "selector": SELECTOR,
            "minimumDistinctParticipants": MINIMUM_DISCLOSURE_PARTICIPANTS,
            "evaluatedAt": self.clock(),
        }
        if not self.generated_only and not authorized:
            raise StudyDataAuthorizationError(
                "study_data_eligibility_authorization_required", 403
            )
        try:
            selection = self.exporter.select_full_night(self.release_id)
        except C2DExportError:
            return {**base, "state": "unavailable"}
        count = selection.stats["participant_count"]
        return {
            **base,
            "state": (
                "eligible"
                if count >= MINIMUM_DISCLOSURE_PARTICIPANTS
                else "under_disclosure_floor"
            ),
            "eligibleBand": _band(count),
            "exclusionBands": {
                "consentOrRelease": _band(
                    selection.stats[
                        "consent_or_release_excluded_participant_count"
                    ]
                ),
                "noQualifyingFullNight": _band(
                    selection.stats[
                        "no_qualifying_full_night_participant_count"
                    ]
                ),
                "qualityOrDuration": _band(
                    selection.stats["ineligible_record_count"]
                ),
            },
        }
