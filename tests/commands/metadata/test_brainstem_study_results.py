from copy import deepcopy
import hashlib
from types import SimpleNamespace

import pytest

from commands.dataunions.brainstem.study_proposals import StudyProposalWorkflow
from commands.dataunions.brainstem.study_results import (
    StudyResultError,
    StudyResultService,
)


AUTHOR = "0x" + "1" * 40
REVIEWERS = ["0x" + value * 40 for value in ("2", "3", "4", "5")]
DIGEST = "sha256:" + "d" * 64
RELEASE_ID = "f" * 64
RELEASE_ID_SHA256 = hashlib.sha256(RELEASE_ID.encode("utf-8")).hexdigest()


class ProposalDao:
    def __init__(self):
        self.document = None

    def create(self, document):
        self.document = deepcopy(document)

    def get(self, _proposal_id):
        return deepcopy(self.document)

    def mutate(self, _proposal_id, mutator):
        self.document = deepcopy(mutator(deepcopy(self.document)))
        return deepcopy(self.document)


class ResultDao:
    def __init__(self):
        self.rows = []

    def append(self, document):
        existing = self.get(document["proposalId"], document["jobIdHash"])
        if existing is not None:
            private = {
                "_id",
                "resultVersion",
                "supersedesResultId",
                "receiptSha256",
                "resultId",
            }
            if {
                key: value for key, value in existing.items() if key not in private
            } != {
                key: value for key, value in document.items() if key not in private
            }:
                raise StudyResultError("study_result_job_reused", 409)
            return deepcopy(existing)
        latest = self.list(document["proposalId"], 1)
        stored = deepcopy(document)
        stored.update(
            {
                "_id": "result-document-{}".format(len(self.rows) + 1),
                "resultVersion": latest[0]["resultVersion"] + 1 if latest else 1,
                "supersedesResultId": latest[0]["resultId"] if latest else None,
                "receiptSha256": "f" * 64,
            }
        )
        self.rows.append(stored)
        return deepcopy(stored)

    def get(self, proposal_id, job_id_hash):
        return next(
            (
                deepcopy(row)
                for row in self.rows
                if row["proposalId"] == proposal_id and row["jobIdHash"] == job_id_hash
            ),
            None,
        )

    def list(self, proposal_id, limit):
        return sorted(
            (row for row in self.rows if row["proposalId"] == proposal_id),
            key=lambda row: row["resultVersion"],
            reverse=True,
        )[:limit]


class AuditDao:
    def __init__(self, audit):
        self.audits = [audit]

    def query_all(self, query):
        selector = query["selector"]
        return [
            deepcopy(audit)
            for audit in self.audits
            if all(audit.get(key) == value for key, value in selector.items())
        ]


def ids():
    counter = 0

    def factory(prefix):
        nonlocal counter
        counter += 1
        return "{}_{}".format(prefix, format(counter, "x"))

    return factory


def reviewed_workflow():
    flow = StudyProposalWorkflow(
        ProposalDao(), clock=lambda: "2026-08-05T00:00:00Z", id_factory=ids()
    )
    proposal = flow.create(
        AUTHOR,
        {
            "title": "Full-night signal compatibility",
            "purpose": "Check whether full-night detector intervals meet a bounded methods contract.",
            "population": "Existing consenting generated Brainstem participants.",
            "participantBurden": "No new task or recording is required for this study.",
            "recordings": "One qualifying full-night sleep recording per participant.",
            "surveyOutline": "No survey is included in this retrospective methods study.",
            "schedule": "One retrospective run.",
            "endpoints": "Aggregate signal quality and compatibility only.",
            "analysisPlan": "Run one reviewed networkless aggregate algorithm with a twenty-person disclosure floor.",
            "retention": "Keep immutable aggregate result receipts and no raw recordings.",
            "resultReturnPlan": "Show aggregate methods findings with explicit limitations.",
            "sourcePapers": ["https://physionet.org/content/apnea-ecg/1.0.0/"],
            "conflicts": "Brainstem commercial interest is disclosed.",
            "offeringId": "brainstem.apdet-retrospective-study",
            "releaseVersion": "1.0.0",
            "releaseSha256": "e" * 64,
        },
    )
    proposal = flow.submit(
        proposal["proposalId"],
        AUTHOR,
        proposal["currentRevisionId"],
        proposal["currentRevisionSha256"],
    )
    for index, (domain, reviewer) in enumerate(
        zip(("scientific", "privacy", "security", "ethics"), REVIEWERS), 1
    ):
        proposal = flow.review(
            proposal["proposalId"],
            reviewer,
            domain,
            "approved",
            proposal["currentRevisionId"],
            proposal["currentRevisionSha256"],
            "Generated review passed.",
            format(index, "x") * 64,
        )
    return flow, proposal


def complete_result():
    return {
        "schema": "brainstem.c2d-result/v1",
        "status": "complete",
        "title": "Full-night signal compatibility",
        "summary": "The 20 to 49 participant group met the signal-quality contract, but official-method input compatibility is not established.",
        "metrics": [
            {"label": "Median recording duration", "value": 5.1, "unit": "hours"},
            {"label": "Median accepted interval share", "value": 100, "unit": "%"},
            {"label": "Median duration coverage", "value": 100, "unit": "%"},
            {
                "label": "Verified normal-to-normal provenance",
                "value": 0,
                "unit": "%",
            },
        ],
        "charts": [
            {
                "type": "bar",
                "title": "Median full-night signal quality",
                "x": {
                    "label": "Quality measure",
                    "values": [
                        "Accepted interval share",
                        "Duration coverage",
                        "Verified normal-to-normal provenance",
                    ],
                },
                "y": {"label": "Share", "unit": "%"},
                "series": [
                    {"label": "Cohort median", "values": [100, 100, 0]}
                ],
            }
        ],
        "table": None,
        "warnings": [
            "Normal-to-normal interval provenance is unverified, so the official method input requirement is not met.",
            "Signal quality only; not apnea detection, screening, diagnosis, reassurance, or medical advice.",
        ],
        "provenance": {
            "algorithmVersion": "0.1.0",
            "algorithmImageDigest": DIGEST,
            "datasetSchemaVersion": "brainstem.full-night-rr-cohort/v1",
            "generatedAt": "2026-08-05T00:02:00Z",
        },
    }


def service(snapshot="c" * 64):
    flow, proposal = reviewed_workflow()
    audit = {
        "document_type": "brainstem_c2d_export_audit",
        "job_id_hash": "a" * 64,
        "outcome": "released",
        "analysis_id": "brainstem.full-night-rr-signal-compatibility/v1",
        "checksum": "b" * 64,
        "source_snapshot_sha256": "c" * 64,
        "study_proposal_id": proposal["proposalId"],
        "study_revision_id": proposal["currentRevisionId"],
        "study_revision_sha256": proposal["currentRevisionSha256"],
        "study_review_decision_sha256": [
            review["decisionSha256"]
            for review in sorted(proposal["reviews"], key=lambda item: item["domain"])
        ],
        "study_release_version": "1.0.0",
        "study_release_sha256": "e" * 64,
        "release_id_hash": RELEASE_ID_SHA256,
        "participant_count": 20,
        "selector_version": "brainstem.full-night-rr-selector/v1",
    }
    result_dao = ResultDao()
    return (
        StudyResultService(
            flow,
            result_dao,
            AuditDao(audit),
            SimpleNamespace(
                select_full_night=lambda _release: SimpleNamespace(
                    source_snapshot_sha256=snapshot,
                    stats={"participant_count": 20},
                )
            ),
            RELEASE_ID,
            DIGEST,
            "1.0.0",
            "e" * 64,
        ),
        proposal,
        result_dao,
    )


def receipt(proposal):
    return {
        "schema": "brainstem.study-result-commit/v1",
        "revisionId": proposal["currentRevisionId"],
        "revisionSha256": proposal["currentRevisionSha256"],
        "jobIdHash": "a" * 64,
        "inputSha256": "b" * 64,
        "sourceSnapshotSha256": "c" * 64,
        "algorithmImageDigest": DIGEST,
        "completedAt": "2026-08-05T00:03:00Z",
        "result": complete_result(),
    }


def test_append_is_idempotent_private_and_reports_new_data():
    results, proposal, stored = service(snapshot="9" * 64)
    first = results.append(proposal["proposalId"], receipt(proposal))
    second = results.append(proposal["proposalId"], receipt(proposal))
    assert first == second
    assert len(stored.rows) == 1
    assert first["resultVersion"] == 1
    assert first["supersedesResultId"] is None
    assert "jobIdHash" not in first
    assert first["resultId"] != "result_" + "a" * 64
    assert "sourceSnapshotSha256" not in first
    assert first["releaseIdSha256"] == RELEASE_ID_SHA256
    assert first["releaseVersion"] == "1.0.0"
    assert first["releaseSha256"] == "e" * 64
    assert first["selectorVersion"] == "brainstem.full-night-rr-selector/v1"
    assert len(first["reviewDecisions"]) == 4
    assert len(first["receiptSha256"]) == 64
    assert results.status(proposal["proposalId"], AUTHOR)["state"] == "rerun_available"


def test_append_accepts_identical_released_audits_from_an_export_retry():
    results, proposal, _stored = service()
    results.audit_dao.audits.append(deepcopy(results.audit_dao.audits[0]))
    assert results.append(proposal["proposalId"], receipt(proposal))["resultVersion"] == 1

    results, proposal, _stored = service()
    conflicting = deepcopy(results.audit_dao.audits[0])
    conflicting["participant_count"] = 50
    results.audit_dao.audits.append(conflicting)
    with pytest.raises(StudyResultError, match="study_result_export_mismatch"):
        results.append(proposal["proposalId"], receipt(proposal))


def test_append_versions_and_supersedes_in_order():
    results, proposal, _stored = service()
    first = results.append(proposal["proposalId"], receipt(proposal))
    second_receipt = receipt(proposal)
    second_receipt.update(
        {
            "jobIdHash": "9" * 64,
            "inputSha256": "8" * 64,
            "sourceSnapshotSha256": "7" * 64,
            "completedAt": "2026-08-05T00:04:00Z",
        }
    )
    results.audit_dao.audits.append(
        {
            "document_type": "brainstem_c2d_export_audit",
            "job_id_hash": "9" * 64,
            "outcome": "released",
            "analysis_id": "brainstem.full-night-rr-signal-compatibility/v1",
            "checksum": "8" * 64,
            "source_snapshot_sha256": "7" * 64,
            "study_proposal_id": proposal["proposalId"],
            "study_revision_id": proposal["currentRevisionId"],
            "study_revision_sha256": proposal["currentRevisionSha256"],
            "study_review_decision_sha256": [
                review["decisionSha256"]
                for review in sorted(
                    proposal["reviews"], key=lambda item: item["domain"]
                )
            ],
            "study_release_version": "1.0.0",
            "study_release_sha256": "e" * 64,
            "release_id_hash": RELEASE_ID_SHA256,
            "participant_count": 20,
            "selector_version": "brainstem.full-night-rr-selector/v1",
        }
    )
    second = results.append(proposal["proposalId"], second_receipt)
    history = results.list(proposal["proposalId"], AUTHOR)
    assert [row["resultVersion"] for row in history] == [2, 1]
    assert second["supersedesResultId"] == first["resultId"]
    status = results.status(proposal["proposalId"], AUTHOR)
    assert status["state"] == "current"
    assert status["latestResultId"] == first["resultId"]


def test_status_suppresses_a_cohort_that_falls_below_the_floor():
    results, proposal, _stored = service()
    results.append(proposal["proposalId"], receipt(proposal))
    results.selector.select_full_night = lambda _release: SimpleNamespace(
        source_snapshot_sha256="c" * 64,
        stats={"participant_count": 19},
    )
    assert (
        results.status(proposal["proposalId"], AUTHOR)["state"]
        == "under_disclosure_floor"
    )


def test_status_reports_rerun_after_the_approved_algorithm_changes():
    results, proposal, _stored = service()
    results.append(proposal["proposalId"], receipt(proposal))
    results.algorithm_digest = "sha256:" + "e" * 64
    assert results.status(proposal["proposalId"], AUTHOR)["state"] == "rerun_available"


def test_status_reports_rerun_after_the_approved_release_changes():
    results, proposal, _stored = service()
    results.append(proposal["proposalId"], receipt(proposal))
    results.release_id = "e" * 64
    assert results.status(proposal["proposalId"], AUTHOR)["state"] == "rerun_available"


def test_status_reports_rerun_after_the_selector_contract_changes():
    results, proposal, stored = service()
    results.append(proposal["proposalId"], receipt(proposal))
    stored.rows[0]["selectorVersion"] = "brainstem.full-night-rr-selector/v0"
    assert results.status(proposal["proposalId"], AUTHOR)["state"] == "rerun_available"


def test_rejects_identifier_bearing_result_and_export_mismatch():
    results, proposal, _stored = service()
    leaked = receipt(proposal)
    leaked["result"]["participantId"] = "hidden"
    with pytest.raises(StudyResultError, match="study_result_invalid"):
        results.append(proposal["proposalId"], leaked)
    leaked_text = receipt(proposal)
    leaked_text["result"]["summary"] = "Participant 0x{} was included.".format("1" * 40)
    with pytest.raises(StudyResultError, match="study_result_invalid"):
        results.append(proposal["proposalId"], leaked_text)
    leaked_source = receipt(proposal)
    leaked_source["result"]["summary"] = "RECORD-CANARY-0001 was included."
    with pytest.raises(StudyResultError, match="study_result_invalid"):
        results.append(proposal["proposalId"], leaked_source)
    mismatched = receipt(proposal)
    mismatched["inputSha256"] = "0" * 64
    with pytest.raises(StudyResultError, match="study_result_export_mismatch"):
        results.append(proposal["proposalId"], mismatched)
    results.audit_dao.audits[0]["study_review_decision_sha256"][0] = "0" * 64
    with pytest.raises(StudyResultError, match="study_result_export_mismatch"):
        results.append(proposal["proposalId"], receipt(proposal))


def test_rejects_an_export_from_a_different_release():
    results, proposal, _stored = service()
    results.audit_dao.audits[0]["release_id_hash"] = "0" * 64
    with pytest.raises(StudyResultError, match="study_result_export_mismatch"):
        results.append(proposal["proposalId"], receipt(proposal))


def test_rejects_a_result_that_misstates_the_exported_cohort_band():
    results, proposal, _stored = service()
    overstated = receipt(proposal)
    overstated["result"]["summary"] = overstated["result"]["summary"].replace(
        "20 to 49", "100 or more"
    )
    with pytest.raises(StudyResultError, match="study_result_invalid"):
        results.append(proposal["proposalId"], overstated)
