from datetime import datetime, timezone
import hashlib
from pathlib import Path
from typing import Any, Dict, List
from uuid import uuid4

from commands.dataunions.brainstem.c2d_export import (
    C2DExportArtifact,
    C2DExportError,
    JOB_ID_PATTERN,
    PSEUDONYM_KEY_ID_PATTERN,
    job_scoped_subject_id,
)
from commands.dataunions.brainstem.consent import has_brainstem_data_consent
from commands.dataunions.brainstem.record_contract import CONTRACT_VERSION
from commands.dataunions.brainstem.record_export import (
    canonical_json,
    resting_rr_record,
)
from commands.dataunions.brainstem.recording_feasibility_study import (
    ASSIGNMENT_POLICY,
    COLLECTION_DAYS,
    CONSENT_CONTENT_SHA256,
    CONSENT_VERSION,
    DATASET_POLICY,
    DATASET_SCHEMA,
    PROTOCOL_VERSION,
    STUDY_ID,
    UTC_FORMAT,
    assignment_window,
    candidate_from_document,
    protocol_sha256,
    select_daily_records,
)


MAX_EXPORT_BYTES = 16 * 1024 * 1024
MAX_PARTICIPANTS = 1_000
MAX_INSPECTED_RECORDS = 20_000


class BrainstemRecordingFeasibilityExporter:
    """Generated-only study materializer; it has no route or persistence owner."""

    def __init__(
        self,
        metadata_dao,
        users_dao,
        enrollment_dao,
        audit_dao,
        upload_root: Path,
        pseudonym_secret: str,
        pseudonym_key_id: str,
        capture_time_verifier,
    ):
        self.metadata_dao = metadata_dao
        self.users_dao = users_dao
        self.enrollment_dao = enrollment_dao
        self.audit_dao = audit_dao
        self.upload_root = Path(upload_root)
        self.pseudonym_secret = pseudonym_secret
        self.pseudonym_key_id = pseudonym_key_id
        self.capture_time_verifier = capture_time_verifier

    def _enrollments(self):
        query = {
            "selector": {
                "document_type": "brainstem_study_enrollment",
                "study_id": STUDY_ID,
            }
        }
        yield from self.enrollment_dao.iter_query(query, batch_size=500)

    def _record_documents(self):
        query = {
            "selector": {
                "file_type": "record",
                "record_contract_version": CONTRACT_VERSION,
                "record_type": "rest",
                "recognized_payloads": {"$elemMatch": {"$eq": "hbr_rr"}},
            },
            "fields": [
                "_id",
                "created_by",
                "file_path",
                "content_hash",
                "file_type",
                "record_contract_version",
                "record_type",
                "recognized_payloads",
                "duration",
                "valid_rr_intervals",
                "accepted_at_utc",
                "captured_at_utc",
            ],
        }
        yield from self.metadata_dao.iter_query(query, batch_size=500)

    def _audit(self, job_id, outcome, stats, **extra):
        job_token = job_id if isinstance(job_id, str) else "<invalid>"
        document = {
            "document_type": "brainstem_recording_feasibility_export_audit",
            "job_id_hash": hashlib.sha256(job_token.encode("utf-8")).hexdigest(),
            "pseudonym_key_id": self.pseudonym_key_id,
            "study_id": STUDY_ID,
            "protocol_sha256": protocol_sha256(),
            "schema": DATASET_SCHEMA,
            "policy": DATASET_POLICY,
            "outcome": outcome,
            "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            **stats,
            **extra,
        }
        self.audit_dao.save(
            f"brainstem-recording-feasibility-audit:{uuid4().hex}", document
        )

    def build(self, job_id: str):
        if not isinstance(job_id, str) or not JOB_ID_PATTERN.fullmatch(job_id):
            raise C2DExportError("invalid_job_id", 400)
        if (
            not isinstance(self.pseudonym_secret, str)
            or len(self.pseudonym_secret) < 32
            or not isinstance(self.pseudonym_key_id, str)
            or not PSEUDONYM_KEY_ID_PATTERN.fullmatch(self.pseudonym_key_id)
            or not callable(self.capture_time_verifier)
        ):
            raise C2DExportError("export_configuration_invalid", 503)

        enrollments = list(self._enrollments())
        if len(enrollments) > MAX_PARTICIPANTS:
            raise C2DExportError("participant_limit_exceeded", 413)
        enrollments.sort(key=lambda item: item.get("user_id", ""))
        user_ids = [item.get("user_id") for item in enrollments]
        if (
            any(not isinstance(user_id, str) or not user_id for user_id in user_ids)
            or len(set(user_ids)) != len(user_ids)
        ):
            raise C2DExportError("enrollment_set_invalid")

        documents = []
        for document in self._record_documents():
            documents.append(document)
            if len(documents) > MAX_INSPECTED_RECORDS:
                raise C2DExportError("inspected_record_limit_exceeded", 413)
        documents.sort(
            key=lambda item: (item.get("created_by", ""), item.get("_id", ""))
        )
        by_owner: Dict[str, List[Dict[str, Any]]] = {}
        for document in documents:
            owner = document.get("created_by")
            if not isinstance(owner, str) or not owner:
                raise C2DExportError("record_owner_invalid")
            by_owner.setdefault(owner, []).append(document)

        participants = []
        excluded_enrollment_count = 0
        ineligible_record_count = 0
        unverified_record_count = 0
        recording_count = 0
        seen_owners = set()
        for enrollment in enrollments:
            user_id = enrollment["user_id"]
            try:
                user = self.users_dao.get_doc_by_id(user_id)
            except Exception:
                excluded_enrollment_count += 1
                continue
            if user.get("_id") != user_id:
                raise C2DExportError("participant_identity_invalid")
            current_consent = has_brainstem_data_consent(user)
            if (
                user.get("is_access_blocked") is True
                or assignment_window(enrollment, current_consent) is None
            ):
                excluded_enrollment_count += 1
                continue
            owner = user.get("public_address")
            if (
                not isinstance(owner, str)
                or not owner
                or owner in seen_owners
            ):
                raise C2DExportError("participant_wallet_invalid")
            seen_owners.add(owner)

            candidates = []
            documents_by_id = {}
            for document in by_owner.get(owner, []):
                record_id = document.get("_id")
                if record_id in documents_by_id:
                    raise C2DExportError("record_set_invalid")
                documents_by_id[record_id] = document
                try:
                    capture_verified = self.capture_time_verifier(document)
                except Exception as exc:
                    raise C2DExportError(
                        "capture_verification_failed", 503
                    ) from exc
                if capture_verified is not True:
                    unverified_record_count += 1
                    continue
                candidate = candidate_from_document(
                    document, capture_time_verified=True
                )
                if candidate is None:
                    ineligible_record_count += 1
                    continue
                candidates.append(candidate)

            selected = select_daily_records(
                candidates,
                enrollment,
                has_current_data_consent=current_consent,
            )
            candidate_by_id = {item.record_id: item for item in candidates}
            recordings = []
            for day_index, record_id in selected:
                document = documents_by_id[record_id]
                candidate = candidate_by_id[record_id]
                source = resting_rr_record(self.upload_root, owner, document)
                if source is None:
                    raise C2DExportError("source_contract_mismatch")
                if (
                    source.captured_at_utc
                    != candidate.captured_at.strftime(UTC_FORMAT)
                    or source.recording["durationSeconds"]
                    != candidate.duration_seconds
                    or source.valid_rr_intervals
                    != candidate.valid_rr_intervals
                    or len(source.recording["rrIntervalsMs"])
                    != candidate.valid_rr_intervals
                ):
                    raise C2DExportError("source_summary_mismatch")
                recordings.append(
                    {
                        "dayIndex": day_index,
                        "durationSeconds": source.recording["durationSeconds"],
                        "rrIntervalsMs": source.recording["rrIntervalsMs"],
                    }
                )

            participants.append(
                {
                    "subjectId": job_scoped_subject_id(
                        self.pseudonym_secret,
                        self.pseudonym_key_id,
                        job_id,
                        user_id,
                        "study",
                    ),
                    "recordings": recordings,
                }
            )
            recording_count += len(recordings)

        participants.sort(key=lambda item: item["subjectId"])
        dataset = {
            "schema": DATASET_SCHEMA,
            "policy": DATASET_POLICY,
            "protocol": {
                "id": STUDY_ID,
                "version": PROTOCOL_VERSION,
                "protocolSha256": protocol_sha256(),
                "consentVersion": CONSENT_VERSION,
                "consentContentSha256": CONSENT_CONTENT_SHA256,
                "assignmentPolicy": ASSIGNMENT_POLICY,
                "collectionDays": COLLECTION_DAYS,
            },
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
        ), {
            "enrollment_count": len(enrollments),
            "participant_count": len(participants),
            "excluded_enrollment_count": excluded_enrollment_count,
            "inspected_record_count": len(documents),
            "ineligible_record_count": ineligible_record_count,
            "unverified_record_count": unverified_record_count,
            "recording_count": recording_count,
        }

    def execute(self, job_id: str):
        stats = {
            "enrollment_count": 0,
            "participant_count": 0,
            "excluded_enrollment_count": 0,
            "inspected_record_count": 0,
            "ineligible_record_count": 0,
            "unverified_record_count": 0,
            "recording_count": 0,
        }
        try:
            artifact, stats = self.build(job_id)
            self._audit(
                job_id,
                "released",
                stats,
                byte_count=len(artifact.body),
                checksum=artifact.checksum,
            )
            return artifact
        except C2DExportError as exc:
            try:
                self._audit(job_id, "rejected", stats, reason=exc.code)
            except Exception as audit_exc:
                raise C2DExportError("audit_failed", 503) from audit_exc
            raise
        except Exception as exc:
            try:
                self._audit(job_id, "failed", stats, reason="internal_error")
            except Exception as audit_exc:
                raise C2DExportError("audit_failed", 503) from audit_exc
            raise C2DExportError("export_failed", 500) from exc
