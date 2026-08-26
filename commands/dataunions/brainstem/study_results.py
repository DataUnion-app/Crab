"""Append-only, aggregate-only result receipts for reviewed Brainstem studies."""

from copy import deepcopy
from datetime import datetime
import hashlib
import math
import re
import secrets

from commands.dataunions.brainstem.study_proposals import reviewed_revision_binding
from commands.dataunions.brainstem.limits import MINIMUM_DISCLOSURE_PARTICIPANTS
from commands.dataunions.brainstem.study_eligibility import SELECTOR
from commands.dataunions.studies.registry import content_sha256


HEX64 = re.compile(r"^[0-9a-f]{64}$")
IMAGE = re.compile(r"^sha256:[0-9a-f]{64}$")
MAX_RESULTS = 100
PROHIBITED_KEYS = {
    "public_address",
    "wallet",
    "subjectId",
    "participantId",
    "recording",
    "recordings",
    "rrIntervalsMs",
    "device",
    "sourceId",
}
METRICS = {
    "Median recording duration": (5, 12, "hours"),
    "Median accepted interval share": (95, 100, "%"),
    "Median duration coverage": (90, 110, "%"),
    "Verified normal-to-normal provenance": (0, 0, "%"),
}
TITLE = "Full-night signal compatibility"
INSUFFICIENT_SUMMARY = "The eligible cohort is too small to release a result."
COMPLETE_SUMMARIES = {
    "The {} participant group met the signal-quality contract, but official-method input compatibility is not established.".format(
        band
    )
    for band in ("20 to 49", "50 to 99", "100 or more")
}
INSUFFICIENT_WARNINGS = [
    "At least 20 eligible participants are required for release.",
    "Signal quality only; not apnea detection or screening.",
]
COMPLETE_WARNINGS = [
    "Normal-to-normal interval provenance is unverified, so the official method input requirement is not met.",
    "Signal quality only; not apnea detection, screening, diagnosis, reassurance, or medical advice.",
]
CHART_TITLE = "Median full-night signal quality"
CHART_CATEGORIES = [
    "Accepted interval share",
    "Duration coverage",
    "Verified normal-to-normal provenance",
]


class StudyResultError(Exception):
    def __init__(self, code, status_code=400):
        self.code = code
        self.status_code = status_code
        super().__init__(code)


def _time(value):
    if not isinstance(value, str) or not value.endswith("Z"):
        return False
    try:
        return (
            datetime.fromisoformat(value[:-1] + "+00:00").utcoffset().total_seconds()
            == 0
        )
    except (TypeError, ValueError):
        return False


def _contains_prohibited(value):
    if isinstance(value, dict):
        return any(
            key in PROHIBITED_KEYS or _contains_prohibited(item)
            for key, item in value.items()
        )
    if isinstance(value, list):
        return any(_contains_prohibited(item) for item in value)
    return False


def _validate_result(value, algorithm_digest, participant_count):
    fields = {
        "schema",
        "status",
        "title",
        "summary",
        "metrics",
        "charts",
        "table",
        "warnings",
        "provenance",
    }
    if (
        not isinstance(value, dict)
        or set(value) != fields
        or _contains_prohibited(value)
    ):
        raise StudyResultError("study_result_invalid")
    provenance = value["provenance"]
    if (
        value["schema"] != "brainstem.c2d-result/v1"
        or value["status"] not in {"complete", "insufficient_data"}
        or value["title"] != TITLE
        or value["summary"]
        not in (COMPLETE_SUMMARIES | {INSUFFICIENT_SUMMARY})
        or not isinstance(value["charts"], list)
        or value["table"] is not None
        or value["warnings"]
        != (
            COMPLETE_WARNINGS
            if value["status"] == "complete"
            else INSUFFICIENT_WARNINGS
        )
        or not isinstance(provenance, dict)
        or set(provenance)
        != {
            "algorithmVersion",
            "algorithmImageDigest",
            "datasetSchemaVersion",
            "generatedAt",
        }
        or provenance["algorithmVersion"] != "0.1.0"
        or provenance["algorithmImageDigest"] != algorithm_digest
        or provenance["datasetSchemaVersion"] != "brainstem.full-night-rr-cohort/v1"
        or not _time(provenance["generatedAt"])
    ):
        raise StudyResultError("study_result_invalid")
    metrics = value["metrics"]
    if participant_count < MINIMUM_DISCLOSURE_PARTICIPANTS:
        if (
            value["status"] != "insufficient_data"
            or metrics != []
            or value["charts"] != []
            or value["summary"] != INSUFFICIENT_SUMMARY
        ):
            raise StudyResultError("study_result_invalid")
        return
    expected_band = (
        "20 to 49"
        if participant_count < 50
        else "50 to 99"
        if participant_count < 100
        else "100 or more"
    )
    expected_summary = (
        "The {} participant group met the signal-quality contract, but official-method input compatibility is not established.".format(
            expected_band
        )
    )
    if value["status"] != "complete" or value["summary"] != expected_summary:
        raise StudyResultError("study_result_invalid")
    if not isinstance(metrics, list) or len(metrics) != len(METRICS):
        raise StudyResultError("study_result_invalid")
    seen = set()
    for metric in metrics:
        if not isinstance(metric, dict) or set(metric) != {"label", "value", "unit"}:
            raise StudyResultError("study_result_invalid")
        bounds = METRICS.get(metric["label"])
        if (
            bounds is None
            or metric["label"] in seen
            or metric["unit"] != bounds[2]
            or isinstance(metric["value"], bool)
            or not isinstance(metric["value"], (int, float))
            or not math.isfinite(metric["value"])
            or not bounds[0] <= metric["value"] <= bounds[1]
        ):
            raise StudyResultError("study_result_invalid")
        seen.add(metric["label"])
    values = {metric["label"]: metric["value"] for metric in metrics}
    if value["charts"] != [
        {
            "type": "bar",
            "title": CHART_TITLE,
            "x": {"label": "Quality measure", "values": CHART_CATEGORIES},
            "y": {"label": "Share", "unit": "%"},
            "series": [
                {
                    "label": "Cohort median",
                    "values": [
                        values["Median accepted interval share"],
                        values["Median duration coverage"],
                        values["Verified normal-to-normal provenance"],
                    ],
                }
            ],
        }
    ]:
        raise StudyResultError("study_result_invalid")


def _public(document):
    return {
        key: deepcopy(document[key])
        for key in (
            "resultId",
            "resultVersion",
            "supersedesResultId",
            "proposalId",
            "revisionId",
            "revisionSha256",
            "resultSha256",
            "receiptSha256",
            "algorithmImageDigest",
            "releaseIdSha256",
            "releaseVersion",
            "releaseSha256",
            "selectorVersion",
            "reviewDecisions",
            "completedAt",
            "result",
        )
    }


class StudyResultService:
    def __init__(
        self,
        proposal_workflow,
        result_dao,
        audit_dao,
        selector,
        release_id,
        algorithm_digest,
        release_version,
        release_sha256,
        offering_id="brainstem.apdet-retrospective-study",
    ):
        self.proposal_workflow = proposal_workflow
        self.result_dao = result_dao
        self.audit_dao = audit_dao
        self.selector = selector
        self.release_id = release_id
        self.algorithm_digest = algorithm_digest
        self.release_version = release_version
        self.release_sha256 = release_sha256
        self.offering_id = offering_id

    def append(self, proposal_id, payload):
        required = {
            "schema",
            "revisionId",
            "revisionSha256",
            "jobIdHash",
            "inputSha256",
            "sourceSnapshotSha256",
            "algorithmImageDigest",
            "completedAt",
            "result",
        }
        if not isinstance(payload, dict) or set(payload) != required:
            raise StudyResultError("study_result_receipt_invalid")
        if (
            payload["schema"] != "brainstem.study-result-commit/v1"
            or any(
                not isinstance(payload[name], str) or not HEX64.fullmatch(payload[name])
                for name in (
                    "jobIdHash",
                    "inputSha256",
                    "sourceSnapshotSha256",
                    "revisionSha256",
                )
            )
            or not isinstance(payload["algorithmImageDigest"], str)
            or not IMAGE.fullmatch(payload["algorithmImageDigest"])
            or payload["algorithmImageDigest"] != self.algorithm_digest
            or not _time(payload["completedAt"])
        ):
            raise StudyResultError("study_result_receipt_invalid")
        document = self.proposal_workflow.dao.get(proposal_id)
        binding = reviewed_revision_binding(
            document,
            proposal_id,
            payload["revisionId"],
            payload["revisionSha256"],
            self.offering_id,
            self.release_version,
            self.release_sha256,
        )
        audits = self.audit_dao.query_all(
            {
                "selector": {
                    "document_type": "brainstem_c2d_export_audit",
                    "job_id_hash": payload["jobIdHash"],
                    "outcome": "released",
                }
            }
        )
        if not audits:
            raise StudyResultError("study_result_export_not_found", 409)
        audit = audits[0]
        audit_binding_fields = (
            "analysis_id",
            "checksum",
            "source_snapshot_sha256",
            "study_proposal_id",
            "study_revision_id",
            "study_revision_sha256",
            "study_review_decision_sha256",
            "study_release_version",
            "study_release_sha256",
            "release_id_hash",
            "participant_count",
            "selector_version",
        )
        audit_binding = {key: audit.get(key) for key in audit_binding_fields}
        if any(
            {key: candidate.get(key) for key in audit_binding_fields}
            != audit_binding
            for candidate in audits[1:]
        ):
            raise StudyResultError("study_result_export_mismatch", 409)
        review_hashes = [item["decisionSha256"] for item in binding["reviewDecisions"]]
        release_id_sha256 = hashlib.sha256(self.release_id.encode("utf-8")).hexdigest()
        if (
            audit.get("analysis_id")
            != "brainstem.full-night-rr-signal-compatibility/v1"
            or audit.get("checksum") != payload["inputSha256"]
            or audit.get("source_snapshot_sha256") != payload["sourceSnapshotSha256"]
            or audit.get("study_proposal_id") != proposal_id
            or audit.get("study_revision_id") != payload["revisionId"]
            or audit.get("study_revision_sha256") != payload["revisionSha256"]
            or audit.get("study_review_decision_sha256") != review_hashes
            or audit.get("study_release_version") != binding["releaseVersion"]
            or audit.get("study_release_sha256") != binding["releaseSha256"]
            or audit.get("release_id_hash") != release_id_sha256
            or isinstance(audit.get("participant_count"), bool)
            or not isinstance(audit.get("participant_count"), int)
            or not MINIMUM_DISCLOSURE_PARTICIPANTS
            <= audit["participant_count"]
            <= 100
            or not isinstance(audit.get("selector_version"), str)
            or not re.fullmatch(
                r"brainstem\.full-night-rr-selector/v[1-9][0-9]*",
                audit["selector_version"],
            )
        ):
            raise StudyResultError("study_result_export_mismatch", 409)
        _validate_result(
            payload["result"], self.algorithm_digest, audit["participant_count"]
        )
        result_sha256 = content_sha256(payload["result"])
        result_id = "result_{}".format(secrets.token_hex(16))
        stored = {
            "type": "brainstem_study_result",
            "schema": "brainstem.study-result/v1",
            "resultId": result_id,
            "proposalId": proposal_id,
            "revisionId": payload["revisionId"],
            "revisionSha256": payload["revisionSha256"],
            "jobIdHash": payload["jobIdHash"],
            "inputSha256": payload["inputSha256"],
            "sourceSnapshotSha256": payload["sourceSnapshotSha256"],
            "resultSha256": result_sha256,
            "algorithmImageDigest": payload["algorithmImageDigest"],
            "releaseIdSha256": audit["release_id_hash"],
            "releaseVersion": binding["releaseVersion"],
            "releaseSha256": binding["releaseSha256"],
            "selectorVersion": audit["selector_version"],
            "reviewDecisions": deepcopy(binding["reviewDecisions"]),
            "completedAt": payload["completedAt"],
            "result": deepcopy(payload["result"]),
        }
        return _public(self.result_dao.append(stored))

    def list(self, proposal_id, actor):
        self.proposal_workflow.get(proposal_id, actor)
        rows = self.result_dao.list(proposal_id, MAX_RESULTS)
        return [_public(row) for row in rows]

    def status(self, proposal_id, actor):
        proposal = self.proposal_workflow.get(proposal_id, actor)
        rows = self.result_dao.list(proposal_id, MAX_RESULTS)
        if not rows:
            return {"state": "no_result", "latestResultId": None}
        revision_rows = [
            row
            for row in rows
            if row["revisionId"] == proposal["currentRevisionId"]
        ]
        if not revision_rows:
            return {
                "state": "review_required",
                "latestResultId": rows[0]["resultId"],
                "revisionId": proposal["currentRevisionId"],
            }
        selected = revision_rows[0]
        try:
            current = self.selector.select_full_night(self.release_id)
            if current.stats["participant_count"] < MINIMUM_DISCLOSURE_PARTICIPANTS:
                state = "under_disclosure_floor"
            else:
                release_id_sha256 = hashlib.sha256(
                    self.release_id.encode("utf-8")
                ).hexdigest()
                matching = next(
                    (
                        row
                        for row in revision_rows
                        if row["sourceSnapshotSha256"]
                        == current.source_snapshot_sha256
                        and row["algorithmImageDigest"] == self.algorithm_digest
                        and row["releaseIdSha256"] == release_id_sha256
                        and row["selectorVersion"] == SELECTOR
                    ),
                    None,
                )
                if matching:
                    state = "current"
                    selected = matching
                else:
                    state = "rerun_available"
        except Exception:
            state = "unavailable"
        return {
            "state": state,
            "latestResultId": selected["resultId"],
            "revisionId": proposal["currentRevisionId"],
        }
