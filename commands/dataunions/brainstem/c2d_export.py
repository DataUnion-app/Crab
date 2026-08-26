from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import hmac
import os
from pathlib import Path
import re
import secrets
import time
from typing import Any, Dict, Iterable, List, Tuple
from uuid import uuid4

from commands.dataunions.brainstem.consent import has_brainstem_data_consent
from commands.dataunions.brainstem.legacy_record_index import (
    has_retrospective_research_consent,
    record_has_legacy_consent,
    retrospective_research_consent_basis,
)
from commands.dataunions.brainstem.cohort_release import (
    CohortReleaseError,
    CohortReleaseService,
    RELEASE_ID_PATTERN,
)
from commands.dataunions.brainstem.record_contract import CONTRACT_VERSION
from commands.dataunions.brainstem.limits import MINIMUM_DISCLOSURE_PARTICIPANTS
from commands.dataunions.brainstem.record_export import (
    RecordExportError,
    canonical_json,
    full_night_rr_record,
    resting_rr_record,
)


JOB_ID_PATTERN = re.compile(r"^[0-9a-f]{64}$")
PSEUDONYM_KEY_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
MAX_EXPORT_BYTES = 16 * 1024 * 1024
MAX_PARTICIPANTS = 1_000
MAX_FULL_NIGHT_PARTICIPANTS = 100
MAX_RECORDINGS_PER_PARTICIPANT = 16
MAX_INSPECTED_RECORDS = 20_000
JOB_RESERVATION_TTL = 600
FULL_NIGHT_SELECTOR_VERSION = "brainstem.full-night-rr-selector/v1"
C2DExportError = RecordExportError


@dataclass(frozen=True)
class CohortInsightPolicy:
    analysis_id: str
    schema: str
    dataset_policy: str | None
    exporter: str
    value_enabled: bool


LEGACY_COHORT_POLICY = CohortInsightPolicy(
    analysis_id="brainstem.resting-rr-cohort-summary/v1",
    schema="brainstem.private-rr-cohort/v1",
    dataset_policy="brainstem.resting-rr/v1",
    exporter="resting_rr",
    value_enabled=True,
)
METHODS_COHORT_POLICY = CohortInsightPolicy(
    analysis_id="brainstem.resting-hrv-methods/v1",
    schema="brainstem.resting-hrv-methods-cohort/v1",
    dataset_policy=None,
    exporter="resting_hrv_methods",
    value_enabled=False,
)
SAMPLE_ENTROPY_COHORT_POLICY = CohortInsightPolicy(
    analysis_id="brainstem.resting-rr-sample-entropy/v1",
    schema="brainstem.resting-sample-entropy-cohort/v1",
    dataset_policy=None,
    exporter="resting_sample_entropy",
    value_enabled=False,
)
APNEA_RETROSPECTIVE_POLICY = CohortInsightPolicy(
    analysis_id="brainstem.apdet-retrospective-evidence/v1",
    schema="brainstem.full-night-rr-cohort/v1",
    dataset_policy="brainstem.apdet-retrospective/v1",
    exporter="full_night_rr",
    value_enabled=False,
)
FULL_NIGHT_COMPATIBILITY_POLICY = CohortInsightPolicy(
    analysis_id="brainstem.full-night-rr-signal-compatibility/v1",
    schema="brainstem.full-night-rr-cohort/v1",
    dataset_policy="brainstem.full-night-rr-signal-compatibility/v1",
    exporter="full_night_rr",
    value_enabled=False,
)

SCHEMA = LEGACY_COHORT_POLICY.schema
POLICY = LEGACY_COHORT_POLICY.dataset_policy


def cohort_insight_policy(
    value: str, generated_only: bool = False
) -> CohortInsightPolicy:
    for policy in (
        LEGACY_COHORT_POLICY,
        METHODS_COHORT_POLICY,
        SAMPLE_ENTROPY_COHORT_POLICY,
        APNEA_RETROSPECTIVE_POLICY,
        FULL_NIGHT_COMPATIBILITY_POLICY,
    ):
        if value == policy.analysis_id:
            if (
                policy is APNEA_RETROSPECTIVE_POLICY
                and os.environ.get("BRAINSTEM_APNEA_REAL_DATA_ENABLED") != "true"
            ):
                raise C2DExportError("analysis_disabled", 503)
            if (
                policy is FULL_NIGHT_COMPATIBILITY_POLICY
                and not generated_only
                and os.environ.get(
                    "BRAINSTEM_FULL_NIGHT_COMPATIBILITY_REAL_DATA_ENABLED"
                )
                != "true"
            ):
                raise C2DExportError("analysis_disabled", 503)
            return policy
    raise C2DExportError("analysis_not_found", 404)


@dataclass(frozen=True)
class C2DExportArtifact:
    body: bytes
    checksum: str
    dataset: Dict[str, Any]
    pseudonym_key_id: str
    private_contributors: Tuple[Dict[str, Any], ...] = ()
    source_snapshot_sha256: str | None = None


@dataclass(frozen=True)
class FullNightCohortSelection:
    rows: Tuple[Dict[str, Any], ...]
    stats: Dict[str, int]
    source_snapshot_sha256: str


def job_scoped_subject_id(
    secret: str,
    key_id: str,
    job_id: str,
    internal_user_id: str,
    domain: str,
) -> str:
    if not JOB_ID_PATTERN.fullmatch(job_id):
        raise C2DExportError("invalid_job_id", 400)
    if not isinstance(key_id, str) or not PSEUDONYM_KEY_ID_PATTERN.fullmatch(key_id):
        raise C2DExportError("invalid_pseudonym_key_id", 500)
    if domain not in {"cohort", "study"}:
        raise C2DExportError("invalid_pseudonym_domain", 500)
    return hmac.new(
        secret.encode("utf-8"),
        (
            f"brainstem.subject.v1\0{key_id}\0{domain}\0{job_id}"
            f"\0{internal_user_id}"
        ).encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def reserve_export_job(audit_dao, domain, job_id, key_id, request_binding):
    job_hash = hashlib.sha256(job_id.encode()).hexdigest()
    doc_id = f"brainstem-c2d-job:{domain}:{job_hash}"
    now = int(time.time())
    lease = secrets.token_hex(16)
    lease_hash = hashlib.sha256(lease.encode()).hexdigest()
    document = {
        "document_type": "brainstem_c2d_job_binding",
        "job_id_hash": job_hash,
        "domain": domain,
        "pseudonym_key_id": key_id,
        "request_binding": request_binding,
        "state": "reserved",
        "lease_sha256": lease_hash,
        "reserved_at": now,
        "expires_at": now + JOB_RESERVATION_TTL,
    }
    try:
        exists, current = audit_dao.get_if_exists(doc_id)
        if not exists:
            try:
                audit_dao.save(doc_id, document)
                return {"state": "reserved", "lease": lease}
            except Exception:
                exists, current = audit_dao.get_if_exists(doc_id)
                if not exists:
                    raise
        if (
            current.get("request_binding") != request_binding
            or current.get("pseudonym_key_id") != key_id
        ):
            raise C2DExportError("job_id_reused", 409)
        if current.get("state") == "completed":
            raise C2DExportError("job_id_completed", 409)

        def reserve(value):
            if (
                value.get("request_binding") != request_binding
                or value.get("pseudonym_key_id") != key_id
            ):
                raise C2DExportError("job_id_reused", 409)
            if (
                value.get("state") == "reserved"
                and value.get("expires_at", 0) > now
            ):
                raise C2DExportError("job_id_in_progress", 409)
            if value.get("state") == "completed":
                return None
            value.pop("finished_at", None)
            value.pop("checksum", None)
            value.update(document)
            return value

        updated = audit_dao.mutate_doc(doc_id, reserve)
        if updated.get("state") == "completed":
            raise C2DExportError("job_id_completed", 409)
        return {"state": "reserved", "lease": lease}
    except C2DExportError:
        raise
    except Exception as exc:
        raise C2DExportError("job_binding_failed", 503) from exc


def finish_export_job(audit_dao, domain, job_id, lease, state, checksum=None):
    doc_id = "brainstem-c2d-job:{}:{}".format(
        domain, hashlib.sha256(job_id.encode()).hexdigest()
    )
    lease_hash = hashlib.sha256(lease.encode()).hexdigest()
    now = int(time.time())

    def finish(document):
        if (
            document.get("state") != "reserved"
            or not hmac.compare_digest(document.get("lease_sha256", ""), lease_hash)
        ):
            raise C2DExportError("job_binding_lost", 409)
        document["state"] = state
        document["finished_at"] = now
        document.pop("lease_sha256", None)
        document.pop("expires_at", None)
        if checksum is not None:
            document["checksum"] = checksum
        else:
            document.pop("checksum", None)
        return document

    try:
        audit_dao.mutate_doc(doc_id, finish)
    except C2DExportError:
        raise
    except Exception as exc:
        raise C2DExportError("job_binding_failed", 503) from exc


class BrainstemC2DExporter:
    def __init__(
        self,
        metadata_dao,
        users_dao,
        audit_dao,
        release_dao,
        upload_root: Path,
        pseudonym_secret: str,
        pseudonym_key_id: str,
        consent_version: str,
        value_service=None,
        policy: CohortInsightPolicy = LEGACY_COHORT_POLICY,
    ):
        self.metadata_dao = metadata_dao
        self.users_dao = users_dao
        self.audit_dao = audit_dao
        self.release_dao = release_dao
        self.upload_root = Path(upload_root)
        self.pseudonym_secret = pseudonym_secret
        self.pseudonym_key_id = pseudonym_key_id
        self.consent_version = consent_version
        self.value_service = value_service
        self.policy = policy

    def _release_service(self):
        return CohortReleaseService(
            self.release_dao,
            self.users_dao,
            self.consent_version,
            purpose=self.policy.dataset_policy or POLICY,
            consent_checker=(
                has_retrospective_research_consent
                if self.policy.exporter == "full_night_rr"
                else has_brainstem_data_consent
            ),
            record_type=(
                "sleep" if self.policy.exporter == "full_night_rr" else "rest"
            ),
        )

    def _record_documents(self) -> Iterable[Dict[str, Any]]:
        record_type = "sleep" if self.policy.exporter == "full_night_rr" else "rest"
        query = {
            "selector": {
                "file_type": "record",
                "record_contract_version": CONTRACT_VERSION,
                "record_type": record_type,
                "recognized_payloads": {"$elemMatch": {"$eq": "hbr_rr"}},
            },
            "fields": [
                "_id",
                "created_by",
                "file_path",
                "content_hash",
                "research_consent_provenance",
            ],
        }
        yield from self.metadata_dao.iter_query(query, batch_size=500)

    def _audit(
        self,
        job_id: str,
        release_id: str,
        outcome: str,
        stats: Dict[str, int],
        **extra,
    ) -> None:
        job_hash = hashlib.sha256(job_id.encode("utf-8")).hexdigest()
        document = {
            "document_type": "brainstem_c2d_export_audit",
            "job_id_hash": job_hash,
            "release_id_hash": hashlib.sha256(release_id.encode("utf-8")).hexdigest(),
            "analysis_id": self.policy.analysis_id,
            "pseudonym_key_id": self.pseudonym_key_id,
            "schema": self.policy.schema,
            "policy": self.policy.dataset_policy,
            "outcome": outcome,
            "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            **stats,
            **extra,
        }
        self.audit_dao.save(f"brainstem-c2d-audit:{uuid4().hex}", document)

    def _study_binding(self, value):
        if self.policy.analysis_id != FULL_NIGHT_COMPATIBILITY_POLICY.analysis_id:
            if value is not None:
                raise C2DExportError("study_binding_not_allowed", 400)
            return None
        if (
            not isinstance(value, dict)
            or set(value)
            != {
                "proposalId",
                "revisionId",
                "revisionSha256",
                "releaseVersion",
                "releaseSha256",
                "reviewDecisions",
            }
            or not re.fullmatch(r"study_[0-9a-f]{1,64}", value.get("proposalId", ""))
            or not re.fullmatch(
                r"revision_[0-9a-f]{1,64}", value.get("revisionId", "")
            )
            or not re.fullmatch(r"[0-9a-f]{64}", value.get("revisionSha256", ""))
            or not re.fullmatch(
                r"[0-9]+\.[0-9]+\.[0-9]+", value.get("releaseVersion", "")
            )
            or not re.fullmatch(r"[0-9a-f]{64}", value.get("releaseSha256", ""))
            or not isinstance(value.get("reviewDecisions"), list)
            or len(value["reviewDecisions"]) != 4
        ):
            raise C2DExportError("study_binding_required", 409)
        decisions = value["reviewDecisions"]
        if (
            any(
                not isinstance(item, dict)
                or set(item) != {"domain", "decisionSha256"}
                or item.get("domain")
                not in {"scientific", "privacy", "security", "ethics"}
                or not re.fullmatch(r"[0-9a-f]{64}", item.get("decisionSha256", ""))
                for item in decisions
            )
            or len({item["domain"] for item in decisions}) != 4
        ):
            raise C2DExportError("study_binding_required", 409)
        return value

    @staticmethod
    def _study_audit(binding):
        if not binding:
            return {}
        return {
            "study_proposal_id": binding["proposalId"],
            "study_revision_id": binding["revisionId"],
            "study_revision_sha256": binding["revisionSha256"],
            "study_release_version": binding["releaseVersion"],
            "study_release_sha256": binding["releaseSha256"],
            "study_review_decision_sha256": [
                item["decisionSha256"] for item in binding["reviewDecisions"]
            ],
        }

    def _request_binding(self, release_id, study_binding=None):
        value = {
            "analysisId": self.policy.analysis_id,
            "releaseId": release_id,
            "schema": self.policy.schema,
        }
        if study_binding:
            value["study"] = study_binding
        return hashlib.sha256(
            canonical_json(value)
        ).hexdigest()

    def select_full_night(self, release_id: str) -> FullNightCohortSelection:
        if self.policy.exporter != "full_night_rr":
            raise C2DExportError("full_night_selector_unavailable", 409)
        if not RELEASE_ID_PATTERN.fullmatch(release_id):
            raise C2DExportError("invalid_release_id", 400)
        try:
            release_members = self._release_service().active_member_ids(release_id)
        except CohortReleaseError as exc:
            raise C2DExportError(exc.code, exc.status_code) from exc

        documents = []
        for document in self._record_documents():
            documents.append(document)
            if len(documents) > MAX_INSPECTED_RECORDS:
                raise C2DExportError("inspected_record_limit_exceeded", 413)
        documents.sort(key=lambda item: (item.get("created_by", ""), item.get("_id", "")))
        by_creator: Dict[str, List[Dict[str, Any]]] = {}
        for document in documents:
            creator = document.get("created_by")
            if not isinstance(creator, str) or not creator:
                raise C2DExportError("record_owner_invalid")
            by_creator.setdefault(creator, []).append(document)

        consent_or_release_excluded = 0
        release_users = []
        release_addresses = set()
        for internal_id in sorted(release_members):
            try:
                user = self.users_dao.get_doc_by_id(internal_id)
            except Exception as exc:
                raise C2DExportError(
                    "participant_lookup_unavailable", 503
                ) from exc
            consent_basis = retrospective_research_consent_basis(user)
            if consent_basis is None:
                consent_or_release_excluded += 1
                continue
            address = user.get("public_address")
            if not isinstance(address, str) or not address or address in release_addresses:
                raise C2DExportError("participant_wallet_invalid")
            release_addresses.add(address)
            release_users.append((internal_id, address, consent_basis))

        selected = []
        no_qualifying_full_night = 0
        ineligible_records = 0
        for internal_id, creator, consent_basis in release_users:
            creator_documents = by_creator.get(creator, [])
            if consent_basis == "legacy_app_gated_consent":
                creator_documents = [
                    document
                    for document in creator_documents
                    if record_has_legacy_consent(document)
                ]
            candidates = []
            for document in creator_documents:
                candidate = full_night_rr_record(self.upload_root, creator, document)
                if candidate is None:
                    ineligible_records += 1
                else:
                    candidates.append((candidate, document))
            if not candidates:
                no_qualifying_full_night += 1
                continue
            candidate, document = sorted(
                candidates,
                key=lambda value: (
                    value[0].captured_at_utc or "",
                    value[0].envelope_timestamp,
                    value[0].content_hash,
                    value[0].source_id,
                ),
            )[-1]
            selected.append({
                "internal_user_id": internal_id,
                "public_address": creator,
                "record_owner": creator,
                "document": document,
                "candidate": candidate,
            })
            # ponytail: current bounded materialization; add chunked aggregation
            # before supporting larger full-night cohorts.
            if len(selected) > MAX_FULL_NIGHT_PARTICIPANTS:
                raise C2DExportError("participant_limit_exceeded", 413)

        current_members = self._release_service().active_member_ids(release_id)
        if current_members != release_members:
            raise C2DExportError("materialization_source_stale", 409)
        for row in selected:
            creator = row["record_owner"]
            expected_document = row["document"]
            expected_source = row["candidate"]
            current_users = self.users_dao.get_by_public_address(creator).get(
                "result", []
            )
            if (
                len(current_users) != 1
                or not has_retrospective_research_consent(current_users[0])
                or current_users[0].get("_id") not in current_members
            ):
                raise C2DExportError("materialization_source_stale", 409)
            try:
                exists, current_document = self.metadata_dao.get_if_exists(
                    expected_document["_id"]
                )
            except Exception as exc:
                raise C2DExportError("record_source_unavailable", 503) from exc
            if not exists or any(
                current_document.get(field) != expected_document.get(field)
                for field in (
                    "_id",
                    "created_by",
                    "file_path",
                    "content_hash",
                    "research_consent_provenance",
                )
            ):
                raise C2DExportError("materialization_source_stale", 409)
            try:
                current_source = full_night_rr_record(
                    self.upload_root, creator, current_document
                )
            except RecordExportError as exc:
                raise C2DExportError("materialization_source_stale", 409) from exc
            if current_source != expected_source:
                raise C2DExportError("materialization_source_stale", 409)

        snapshot = hashlib.sha256(canonical_json([
            {
                "internalUserId": row["internal_user_id"],
                "sourceId": row["candidate"].source_id,
                "contentSha256": row["candidate"].content_hash,
            }
            for row in sorted(selected, key=lambda value: value["internal_user_id"])
        ])).hexdigest()
        return FullNightCohortSelection(
            rows=tuple(selected),
            stats={
                "inspected_record_count": len(documents),
                "consent_or_release_excluded_participant_count": consent_or_release_excluded,
                "no_qualifying_full_night_participant_count": no_qualifying_full_night,
                "ineligible_record_count": ineligible_records,
                "participant_count": len(selected),
                "recording_count": len(selected),
            },
            source_snapshot_sha256=snapshot,
        )

    def _build_full_night(self, job_id, release_id):
        selection = self.select_full_night(release_id)
        participants = []
        contributors = []
        for row in selection.rows:
            candidate = row["candidate"]
            participants.append({
                "subjectId": job_scoped_subject_id(
                    self.pseudonym_secret,
                    self.pseudonym_key_id,
                    job_id,
                    row["internal_user_id"],
                    "study",
                ),
                "recordings": [candidate.recording],
            })
            contributors.append({
                "internal_user_id": row["internal_user_id"],
                "public_address": row["public_address"],
                "record_owner": row["record_owner"],
                "records": [{
                    "id": candidate.source_id,
                    "content_sha256": candidate.content_hash,
                }],
            })
        participants.sort(key=lambda item: item["subjectId"])
        if len(participants) < MINIMUM_DISCLOSURE_PARTICIPANTS:
            raise C2DExportError("participant_privacy_floor", 409)
        dataset = {
            "schema": self.policy.schema,
            "policy": self.policy.dataset_policy,
            "participants": participants,
        }
        body = canonical_json(dataset)
        if len(body) > MAX_EXPORT_BYTES:
            raise C2DExportError("export_byte_limit_exceeded", 413)
        return C2DExportArtifact(
            body=body,
            checksum=hashlib.sha256(body).hexdigest(),
            dataset=dataset,
            pseudonym_key_id=self.pseudonym_key_id,
            private_contributors=tuple(contributors),
            source_snapshot_sha256=selection.source_snapshot_sha256,
        ), selection.stats

    def build(
        self, job_id: str, release_id: str
    ) -> Tuple[C2DExportArtifact, Dict[str, int]]:
        if not JOB_ID_PATTERN.fullmatch(job_id):
            raise C2DExportError("invalid_job_id", 400)
        if (
            not isinstance(self.pseudonym_secret, str)
            or len(self.pseudonym_secret) < 32
            or not isinstance(self.pseudonym_key_id, str)
            or not PSEUDONYM_KEY_ID_PATTERN.fullmatch(self.pseudonym_key_id)
        ):
            raise C2DExportError("export_configuration_invalid", 503)
        if not RELEASE_ID_PATTERN.fullmatch(release_id):
            raise C2DExportError("invalid_release_id", 400)
        if self.policy.exporter == "full_night_rr":
            return self._build_full_night(job_id, release_id)
        try:
            release_members = CohortReleaseService(
                self.release_dao,
                self.users_dao,
                self.consent_version,
                purpose=self.policy.dataset_policy or POLICY,
            ).active_member_ids(release_id)
        except CohortReleaseError as exc:
            raise C2DExportError(exc.code, exc.status_code) from exc

        documents = []
        for document in self._record_documents():
            documents.append(document)
            if len(documents) > MAX_INSPECTED_RECORDS:
                raise C2DExportError("inspected_record_limit_exceeded", 413)
        documents.sort(key=lambda item: (item.get("created_by", ""), item.get("_id", "")))

        by_creator: Dict[str, List[Dict[str, Any]]] = {}
        for document in documents:
            creator = document.get("created_by")
            if not isinstance(creator, str) or not creator:
                raise C2DExportError("record_owner_invalid")
            by_creator.setdefault(creator, []).append(document)

        participants = []
        consent_excluded = 0
        ineligible_record_count = 0
        recording_count = 0
        private_contributors = []
        selected_sources = []
        for creator, creator_documents in by_creator.items():
            users = self.users_dao.get_by_public_address(creator).get("result", [])
            if len(users) != 1 or not has_brainstem_data_consent(users[0]):
                consent_excluded += 1
                continue
            user = users[0]
            internal_id = user.get("_id")
            if not isinstance(internal_id, str) or not internal_id:
                raise C2DExportError("internal_user_id_invalid")
            if internal_id not in release_members:
                continue

            recordings = []
            contributing_records = []
            sample_entropy_candidates = []
            full_night_candidates = []
            for document in creator_documents:
                candidate = (
                    full_night_rr_record(self.upload_root, creator, document)
                    if self.policy.exporter == "full_night_rr"
                    else resting_rr_record(self.upload_root, creator, document)
                )
                if candidate is None:
                    ineligible_record_count += 1
                    continue
                if (
                    self.policy.exporter == "resting_hrv_methods"
                    and (
                        candidate.recording["durationSeconds"] > 360
                        or len(candidate.recording["rrIntervalsMs"]) < 180
                        or abs(
                            sum(candidate.recording["rrIntervalsMs"]) / 1000
                            - candidate.recording["durationSeconds"]
                        )
                        > max(5, candidate.recording["durationSeconds"] * 0.1)
                    )
                ):
                    ineligible_record_count += 1
                    continue
                if (
                    self.policy.exporter == "resting_sample_entropy"
                    and (
                        candidate.recording["durationSeconds"] > 360
                        or len(candidate.recording["rrIntervalsMs"]) < 240
                        or len(candidate.recording["rrIntervalsMs"]) > 900
                        or any(
                            not 300 <= interval <= 2000
                            for interval in candidate.recording["rrIntervalsMs"]
                        )
                        or abs(
                            sum(candidate.recording["rrIntervalsMs"]) / 1000
                            - candidate.recording["durationSeconds"]
                        )
                        > max(5, candidate.recording["durationSeconds"] * 0.1)
                    )
                ):
                    ineligible_record_count += 1
                    continue
                if self.policy.exporter == "resting_sample_entropy":
                    sample_entropy_candidates.append((candidate, document))
                    continue
                if self.policy.exporter == "full_night_rr":
                    full_night_candidates.append((candidate, document))
                    continue
                recordings.append(candidate.recording)
                contributing_records.append({
                    "id": candidate.source_id,
                    "content_sha256": candidate.content_hash,
                })
                selected_sources.append((creator, document, candidate))
                if len(recordings) > MAX_RECORDINGS_PER_PARTICIPANT:
                    raise C2DExportError("recording_limit_exceeded", 413)

            if sample_entropy_candidates:
                candidate, document = sorted(
                    sample_entropy_candidates,
                    key=lambda value: (
                        value[0].envelope_timestamp,
                        value[0].content_hash,
                        value[0].source_id,
                    ),
                )[-1]
                recordings = [candidate.recording]
                contributing_records = [{
                    "id": candidate.source_id,
                    "content_sha256": candidate.content_hash,
                }]
                selected_sources.append((creator, document, candidate))
            if full_night_candidates:
                candidate, document = sorted(
                    full_night_candidates,
                    key=lambda value: (
                        value[0].captured_at_utc or "",
                        value[0].envelope_timestamp,
                        value[0].content_hash,
                        value[0].source_id,
                    ),
                )[-1]
                recordings = [candidate.recording]
                contributing_records = [{
                    "id": candidate.source_id,
                    "content_sha256": candidate.content_hash,
                }]
                selected_sources.append((creator, document, candidate))
            if not recordings:
                continue
            recordings.sort(
                key=lambda item: hashlib.sha256(canonical_json(item)).hexdigest()
            )
            participants.append({
                "subjectId": job_scoped_subject_id(
                    self.pseudonym_secret,
                    self.pseudonym_key_id,
                    job_id,
                    internal_id,
                    (
                        "study"
                        if self.policy.exporter == "full_night_rr"
                        else "cohort"
                    ),
                ),
                "recordings": recordings,
            })
            public_address = user.get("public_address")
            if not isinstance(public_address, str) or not public_address:
                raise C2DExportError("participant_wallet_invalid")
            private_contributors.append({
                "internal_user_id": internal_id,
                "public_address": public_address,
                "record_owner": creator,
                "records": contributing_records,
            })
            recording_count += len(recordings)
            if len(participants) > MAX_PARTICIPANTS:
                raise C2DExportError("participant_limit_exceeded", 413)

        participants.sort(key=lambda item: item["subjectId"])
        if len(participants) < MINIMUM_DISCLOSURE_PARTICIPANTS:
            raise C2DExportError("participant_privacy_floor", 409)
        current_members = CohortReleaseService(
            self.release_dao,
            self.users_dao,
            self.consent_version,
            purpose=self.policy.dataset_policy or POLICY,
        ).active_member_ids(release_id)
        if current_members != release_members:
            raise C2DExportError("materialization_source_stale", 409)
        for creator, expected_document, expected_source in selected_sources:
            current_users = self.users_dao.get_by_public_address(creator).get(
                "result", []
            )
            if (
                len(current_users) != 1
                or not has_brainstem_data_consent(current_users[0])
                or current_users[0].get("_id") not in current_members
            ):
                raise C2DExportError("materialization_source_stale", 409)
            try:
                exists, current_document = self.metadata_dao.get_if_exists(
                    expected_document["_id"]
                )
            except Exception as exc:
                raise C2DExportError("record_source_unavailable", 503) from exc
            if not exists or any(
                current_document.get(field) != expected_document.get(field)
                for field in ("_id", "created_by", "file_path", "content_hash")
            ):
                raise C2DExportError("materialization_source_stale", 409)
            try:
                current_source = (
                    full_night_rr_record(self.upload_root, creator, current_document)
                    if self.policy.exporter == "full_night_rr"
                    else resting_rr_record(self.upload_root, creator, current_document)
                )
            except RecordExportError as exc:
                raise C2DExportError("materialization_source_stale", 409) from exc
            if current_source != expected_source:
                raise C2DExportError("materialization_source_stale", 409)
        dataset = {"schema": self.policy.schema, "participants": participants}
        if self.policy.dataset_policy is not None:
            dataset["policy"] = self.policy.dataset_policy
        body = canonical_json(dataset)
        if len(body) > MAX_EXPORT_BYTES:
            raise C2DExportError("export_byte_limit_exceeded", 413)
        return C2DExportArtifact(
            body=body,
            checksum=hashlib.sha256(body).hexdigest(),
            dataset=dataset,
            pseudonym_key_id=self.pseudonym_key_id,
            private_contributors=tuple(private_contributors),
        ), {
            "inspected_record_count": len(documents),
            "consent_excluded_participant_count": consent_excluded,
            "ineligible_record_count": ineligible_record_count,
            "participant_count": len(participants),
            "recording_count": recording_count,
        }

    def execute(
        self, job_id: str, release_id: str, study_binding=None
    ) -> C2DExportArtifact:
        stats = {
            "inspected_record_count": 0,
            "consent_excluded_participant_count": 0,
            "ineligible_record_count": 0,
            "participant_count": 0,
            "recording_count": 0,
        }
        reservation = None
        binding = None
        try:
            if not isinstance(job_id, str) or not JOB_ID_PATTERN.fullmatch(job_id):
                raise C2DExportError("invalid_job_id", 400)
            binding = self._study_binding(study_binding)
            reservation = reserve_export_job(
                self.audit_dao,
                "cohort",
                job_id,
                self.pseudonym_key_id,
                self._request_binding(release_id, binding),
            )
            artifact, stats = self.build(job_id, release_id)
            if self.value_service is not None and self.policy.value_enabled:
                try:
                    self.value_service.record_export(
                        job_id,
                        release_id,
                        artifact.checksum,
                        self.policy.schema,
                        self.policy.dataset_policy,
                        artifact.private_contributors,
                    )
                except Exception as exc:
                    raise C2DExportError("value_manifest_failed", 503) from exc
            self._audit(
                job_id,
                release_id,
                "released",
                stats,
                byte_count=len(artifact.body),
                checksum=artifact.checksum,
                **(
                    {
                        "source_snapshot_sha256": artifact.source_snapshot_sha256,
                        "selector_version": FULL_NIGHT_SELECTOR_VERSION,
                    }
                    if artifact.source_snapshot_sha256
                    else {}
                ),
                **self._study_audit(binding),
            )
            finish_export_job(
                self.audit_dao,
                "cohort",
                job_id,
                reservation["lease"],
                "completed",
                artifact.checksum,
            )
            return artifact
        except C2DExportError as exc:
            try:
                if reservation and reservation.get("state") == "reserved":
                    finish_export_job(
                        self.audit_dao,
                        "cohort",
                        job_id,
                        reservation["lease"],
                        "failed",
                    )
                self._audit(
                    job_id,
                    release_id,
                    "rejected",
                    stats,
                    reason=exc.code,
                    **self._study_audit(binding),
                )
            except Exception as audit_exc:
                raise C2DExportError("audit_failed", 503) from audit_exc
            raise
        except Exception as exc:
            try:
                if reservation and reservation.get("state") == "reserved":
                    finish_export_job(
                        self.audit_dao,
                        "cohort",
                        job_id,
                        reservation["lease"],
                        "failed",
                    )
                self._audit(
                    job_id,
                    release_id,
                    "failed",
                    stats,
                    reason="internal_error",
                    **self._study_audit(binding),
                )
            except Exception as audit_exc:
                raise C2DExportError("audit_failed", 503) from audit_exc
            raise C2DExportError("export_failed", 500) from exc
