"""Closed, purpose-bound materialization for activated Brainstem studies."""

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
from pathlib import Path
import re
from uuid import uuid4

from commands.dataunions.brainstem.c2d_export import (
    C2DExportArtifact,
    C2DExportError,
    JOB_ID_PATTERN,
    PSEUDONYM_KEY_ID_PATTERN,
    finish_export_job,
    job_scoped_subject_id,
    reserve_export_job,
)
from commands.dataunions.brainstem.generic_study_service import (
    GenericStudyServiceError,
)
from commands.dataunions.brainstem.record_contract import CONTRACT_VERSION
from commands.dataunions.brainstem.record_export import canonical_json, resting_rr_record
from commands.dataunions.brainstem.study_activation import StudyActivationError
from commands.dataunions.brainstem.study_contract import (
    ASSIGNMENT_VERSION,
    COLLECTION_DAYS,
    CONSENT_VERSION,
    PROTOCOL_VERSION,
    STUDY_ID,
    SURVEY_VERSION,
    candidate_from_document,
    protocol_sha256,
    select_daily_records,
    survey_sha256,
    consent_sha256,
)
from commands.dataunions.brainstem.study_operations import StudyOperationsError
from commands.dataunions.brainstem.study_registry import DEFAULT_STUDY_REGISTRY
from commands.dataunions.studies.registry import StudyRegistryError, content_sha256


MAX_SOURCE_STATES = 10_000
MATERIALIZATION_SCHEMA = "brainstem.study-materialization-request/v1"
PROVENANCE_SCHEMA = "brainstem.study-materialization-provenance/v1"
SOURCE_ADAPTER = "brainstem.recording-feasibility-source/v1"
PROPOSAL_ID = re.compile(r"^study_[0-9a-f]{1,64}$")
PERMIT_ID = re.compile(r"^permit_[0-9a-f]{32}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
IMAGE_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")

REQUEST_FIELDS = {
    "schema",
    "jobId",
    "pseudonymKeyId",
    "proposalId",
    "permitId",
    "permitSha256",
    "operationStateSha256",
    "offeringId",
    "releaseVersion",
    "releaseSha256",
    "purposeSha256",
    "surveySha256",
    "participantInformationSha256",
    "protocolSha256",
    "datasetViewSha256",
    "taskPlanSha256",
    "activationProfileSha256",
    "datasetCapability",
    "algorithmId",
    "algorithmVersion",
    "algorithmSourceSha256",
    "algorithmImageDigest",
    "approvedManifestSha256",
    "referenceSha256",
    "resultContractId",
    "resultContractSha256",
    "operationalPolicyId",
    "operationalPolicySha256",
    "limitsSha256",
    "requestSha256",
}


def _request_sha256(value):
    return content_sha256(
        {key: item for key, item in value.items() if key != "requestSha256"}
    )


class BrainstemStudyExporter:
    """Materialize one exact activation request through a code-owned adapter."""

    def __init__(
        self,
        metadata_dao,
        users_dao,
        study_dao,
        audit_dao,
        upload_root: Path,
        pseudonym_secret: str,
        pseudonym_key_id: str,
        capture_time_verifier,
        *,
        activation_service,
        operations_service,
        enrollment_service,
        registry=DEFAULT_STUDY_REGISTRY,
    ):
        self.metadata_dao = metadata_dao
        self.users_dao = users_dao
        self.study_dao = study_dao
        self.audit_dao = audit_dao
        self.upload_root = Path(upload_root)
        self.pseudonym_secret = pseudonym_secret
        self.pseudonym_key_id = pseudonym_key_id
        self.capture_time_verifier = capture_time_verifier
        self.activation_service = activation_service
        self.operations_service = operations_service
        self.enrollment_service = enrollment_service
        self.registry = registry

    def _configuration(self):
        if (
            not isinstance(self.pseudonym_secret, str)
            or len(self.pseudonym_secret) < 32
            or not isinstance(self.pseudonym_key_id, str)
            or not PSEUDONYM_KEY_ID_PATTERN.fullmatch(self.pseudonym_key_id)
            or not callable(self.capture_time_verifier)
            or self.activation_service is None
            or self.operations_service is None
            or self.enrollment_service is None
        ):
            raise C2DExportError("export_configuration_invalid", 503)

    def _authority(self, proposal_id, permit_id):
        try:
            permit = self.activation_service.load_verified_permit(
                proposal_id, permit_id
            )
            status = self.operations_service.load_verified_operation(
                proposal_id, permit_id, "materialization"
            )
            state = status["state"]
            if (
                state["proposalId"] != proposal_id
                or state["permitId"] != permit_id
                or state["permitSha256"] != permit["permitSha256"]
                or state["lifecycleState"] != "active"
                or state["disposition"] != "current"
            ):
                raise C2DExportError("study_not_active", 409)
            release = self.registry.release(
                state["offeringId"],
                state["releaseVersion"],
                state["releaseSha256"],
            )
            profile = self.registry.activation_profile(
                release["offeringId"],
                release["releaseVersion"],
                release["releaseSha256"],
            )
            task_plan = self.registry.task_plan(
                release["offeringId"],
                release["releaseVersion"],
                release["releaseSha256"],
            )
            survey = self.registry.artifact(release["survey"])
            dataset_view = self.registry.artifact(release["datasetView"])
            profile_values = profile["content"]
            if (
                permit["bundle"]["release"]["releaseSha256"]
                != release["releaseSha256"]
                or permit["bundle"]["activationProfile"] != profile
                or state["taskPlan"] != release["taskPlan"]
                or task_plan["sha256"] != release["taskPlan"]["sha256"]
                or dataset_view["content"]["adapterCapability"]
                != profile_values["datasetCapability"]
                or profile_values["environment"] != "generated-local"
                or profile_values["dataMode"] != "generated_only"
                or profile_values["algorithmNetwork"] != "none"
                or survey["content"]["clinicalVerification"] is not False
            ):
                raise C2DExportError("study_authority_invalid", 409)
        except C2DExportError:
            raise
        except StudyOperationsError as error:
            if error.code == "study_operation_not_allowed":
                raise C2DExportError("study_not_active", 409) from error
            raise C2DExportError("study_authority_invalid", 409) from error
        except (
            KeyError,
            StudyActivationError,
            StudyRegistryError,
        ) as error:
            raise C2DExportError("study_authority_invalid", 409) from error
        return {
            "permit": permit,
            "status": status,
            "state": state,
            "release": release,
            "profile": profile,
            "taskPlan": task_plan,
            "datasetView": dataset_view,
        }

    def _request(self, job_id, authority):
        state = authority["state"]
        permit = authority["permit"]
        release = authority["release"]
        profile = authority["profile"]
        values = profile["content"]
        request = {
            "schema": MATERIALIZATION_SCHEMA,
            "jobId": job_id,
            "pseudonymKeyId": self.pseudonym_key_id,
            "proposalId": state["proposalId"],
            "permitId": state["permitId"],
            "permitSha256": permit["permitSha256"],
            "operationStateSha256": state["stateSha256"],
            "offeringId": release["offeringId"],
            "releaseVersion": release["releaseVersion"],
            "releaseSha256": release["releaseSha256"],
            "purposeSha256": release["purpose"]["sha256"],
            "surveySha256": release["survey"]["sha256"],
            "participantInformationSha256": release["participantInformation"][
                "sha256"
            ],
            "protocolSha256": release["protocol"]["sha256"],
            "datasetViewSha256": release["datasetView"]["sha256"],
            "taskPlanSha256": release["taskPlan"]["sha256"],
            "activationProfileSha256": release["activationProfile"]["sha256"],
            "datasetCapability": values["datasetCapability"],
            "algorithmId": values["algorithmId"],
            "algorithmVersion": values["algorithmVersion"],
            "algorithmSourceSha256": values["algorithmSourceSha256"],
            "algorithmImageDigest": values["algorithmImageDigest"],
            "approvedManifestSha256": values["approvedManifestSha256"],
            "referenceSha256": values["referenceSha256"],
            "resultContractId": values["resultContractId"],
            "resultContractSha256": values["resultContractSha256"],
            "operationalPolicyId": values["operationalPolicyId"],
            "operationalPolicySha256": values["operationalPolicySha256"],
            "limitsSha256": content_sha256(values["limits"]),
            "requestSha256": None,
        }
        request["requestSha256"] = _request_sha256(request)
        return request

    def create_request(self, job_id, proposal_id, permit_id):
        self._configuration()
        if not isinstance(job_id, str) or not JOB_ID_PATTERN.fullmatch(job_id):
            raise C2DExportError("invalid_job_id", 400)
        if (
            not isinstance(proposal_id, str)
            or not PROPOSAL_ID.fullmatch(proposal_id)
            or not isinstance(permit_id, str)
            or not PERMIT_ID.fullmatch(permit_id)
        ):
            raise C2DExportError("study_authority_invalid", 409)
        return self._request(job_id, self._authority(proposal_id, permit_id))

    def _validate_request(self, request):
        if (
            not isinstance(request, dict)
            or set(request) != REQUEST_FIELDS
            or request.get("schema") != MATERIALIZATION_SCHEMA
            or not isinstance(request.get("jobId"), str)
            or not JOB_ID_PATTERN.fullmatch(request["jobId"])
            or request.get("pseudonymKeyId") != self.pseudonym_key_id
            or not isinstance(request.get("proposalId"), str)
            or not PROPOSAL_ID.fullmatch(request["proposalId"])
            or not isinstance(request.get("permitId"), str)
            or not PERMIT_ID.fullmatch(request["permitId"])
            or any(
                not isinstance(request.get(field), str)
                or not SHA256.fullmatch(request[field])
                for field in (
                    "permitSha256",
                    "operationStateSha256",
                    "releaseSha256",
                    "purposeSha256",
                    "surveySha256",
                    "participantInformationSha256",
                    "protocolSha256",
                    "datasetViewSha256",
                    "taskPlanSha256",
                    "activationProfileSha256",
                    "algorithmSourceSha256",
                    "approvedManifestSha256",
                    "referenceSha256",
                    "resultContractSha256",
                    "operationalPolicySha256",
                    "limitsSha256",
                    "requestSha256",
                )
            )
            or not isinstance(request.get("algorithmImageDigest"), str)
            or not IMAGE_DIGEST.fullmatch(request["algorithmImageDigest"])
            or request["requestSha256"] != _request_sha256(request)
        ):
            raise C2DExportError("materialization_request_invalid", 400)
        return self._current_bound_authority(request)

    def _current_bound_authority(self, request):
        authority = self._authority(request["proposalId"], request["permitId"])
        if request != self._request(request["jobId"], authority):
            raise C2DExportError("materialization_request_stale", 409)
        return authority

    def _record_documents(self, owners, maximum_total_recordings):
        query = {
            "selector": {
                "file_type": "record",
                "record_contract_version": CONTRACT_VERSION,
                "record_type": "rest",
                "recognized_payloads": {"$elemMatch": {"$eq": "hbr_rr"}},
                "created_by": {"$in": sorted(owners)},
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
        count = 0
        for document in self.metadata_dao.iter_query(query, batch_size=500):
            count += 1
            if count > maximum_total_recordings:
                raise C2DExportError("record_limit_exceeded", 413)
            yield document

    def _current_record(self, discovered):
        record_id = discovered.get("_id")
        if not isinstance(record_id, str) or not record_id:
            raise C2DExportError("record_set_invalid")
        try:
            exists, current = self.metadata_dao.get_if_exists(record_id)
        except Exception as error:
            raise C2DExportError("record_source_unavailable", 503) from error
        if not exists:
            return None
        fields = (
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
        )
        if not isinstance(current, dict) or any(
            current.get(field) != discovered.get(field) for field in fields
        ):
            raise C2DExportError("record_source_changed", 409)
        return current

    @staticmethod
    def _selection_enrollment(enrollment):
        """Converge the signed generic enrollment on the reviewed v1 selector."""
        return {
            "studyId": STUDY_ID,
            "protocolVersion": PROTOCOL_VERSION,
            "protocolSha256": protocol_sha256(),
            "surveyVersion": SURVEY_VERSION,
            "surveySha256": survey_sha256(),
            "consentVersion": CONSENT_VERSION,
            "consentSha256": consent_sha256(),
            "assignmentVersion": ASSIGNMENT_VERSION,
            "state": "active",
            "startsAt": enrollment["startsAt"],
            "endsAt": enrollment["endsAt"],
        }

    def _eligible_roster(self, authority, limits):
        release = authority["release"]
        state = authority["state"]
        try:
            rows = self.study_dao.materialization_states(
                release["offeringId"], MAX_SOURCE_STATES + 1
            )
        except Exception as error:
            raise C2DExportError("study_state_unavailable", 503) from error
        if len(rows) > MAX_SOURCE_STATES:
            raise C2DExportError("study_state_limit_exceeded", 413)
        rows.sort(key=lambda item: item.get("user_id", ""))
        user_ids = [item.get("user_id") for item in rows]
        if (
            any(not isinstance(user_id, str) or not user_id for user_id in user_ids)
            or len(set(user_ids)) != len(user_ids)
        ):
            raise C2DExportError("study_state_invalid")
        roster = []
        owners = set()
        excluded = 0
        for row in rows:
            user_id = row["user_id"]
            try:
                user = self.users_dao.get_doc_by_id(user_id)
            except Exception as error:
                raise C2DExportError(
                    "participant_source_unavailable", 503
                ) from error
            try:
                enrollment = self.enrollment_service.load_verified_enrollment(
                    user_id,
                    release["offeringId"],
                    user=user,
                )
            except GenericStudyServiceError as error:
                if error.status_code >= 500:
                    raise C2DExportError(
                        "enrollment_source_unavailable", 503
                    ) from error
                excluded += 1
                continue
            except Exception as error:
                raise C2DExportError(
                    "enrollment_source_unavailable", 503
                ) from error
            if (
                enrollment.get("proposalId") != state["proposalId"]
                or enrollment.get("permitId") != state["permitId"]
                or enrollment.get("releaseVersion") != release["releaseVersion"]
                or enrollment.get("releaseSha256") != release["releaseSha256"]
                or enrollment.get("taskPlan") != state["taskPlan"]
                or enrollment.get("state") != "active"
                or type(enrollment.get("startsAt")) is not int
                or type(enrollment.get("endsAt")) is not int
                or enrollment["endsAt"] - enrollment["startsAt"]
                != COLLECTION_DAYS * 86400
            ):
                excluded += 1
                continue
            owner = user.get("public_address")
            if not isinstance(owner, str) or not owner or owner in owners:
                raise C2DExportError("participant_wallet_invalid")
            owners.add(owner)
            roster.append((user_id, owner, enrollment))
            if len(roster) > limits["maximumParticipants"]:
                raise C2DExportError("participant_limit_exceeded", 413)
        return roster, excluded

    def _final_current_barrier(
        self,
        request,
        authority,
        limits,
        roster,
        selected_records,
    ):
        current_authority = self._current_bound_authority(request)
        if current_authority["state"] != authority["state"]:
            raise C2DExportError("materialization_request_stale", 409)
        current_roster, _excluded = self._eligible_roster(
            current_authority, limits
        )
        if current_roster != roster:
            raise C2DExportError("materialization_source_stale", 409)
        for owner, expected_document, expected_source in selected_records:
            current_document = self._current_record(expected_document)
            if current_document is None:
                raise C2DExportError("materialization_source_stale", 409)
            try:
                current_source = resting_rr_record(
                    self.upload_root, owner, current_document
                )
            except C2DExportError as error:
                raise C2DExportError(
                    "materialization_source_stale", 409
                ) from error
            if current_source != expected_source:
                raise C2DExportError("materialization_source_stale", 409)

    def _provenance(self, request, roster_sha256=None, record_set_sha256=None):
        request_authority = {
            key: value
            for key, value in request.items()
            if key not in {"jobId", "pseudonymKeyId", "requestSha256"}
        }
        return {
            "schema": PROVENANCE_SCHEMA,
            "sourceAdapter": SOURCE_ADAPTER,
            "authorityRequestSha256": content_sha256(request_authority),
            "permitSha256": request["permitSha256"],
            "operationStateSha256": request["operationStateSha256"],
            "releaseSha256": request["releaseSha256"],
            "purposeSha256": request["purposeSha256"],
            "surveySha256": request["surveySha256"],
            "participantInformationSha256": request[
                "participantInformationSha256"
            ],
            "protocolSha256": request["protocolSha256"],
            "datasetViewSha256": request["datasetViewSha256"],
            "taskPlanSha256": request["taskPlanSha256"],
            "activationProfileSha256": request["activationProfileSha256"],
            "algorithmSourceSha256": request["algorithmSourceSha256"],
            "algorithmImageDigest": request["algorithmImageDigest"],
            "approvedManifestSha256": request["approvedManifestSha256"],
            "referenceSha256": request["referenceSha256"],
            "resultContractSha256": request["resultContractSha256"],
            "operationalPolicySha256": request["operationalPolicySha256"],
            "limitsSha256": request["limitsSha256"],
            "rosterSha256": roster_sha256,
            "recordSetSha256": record_set_sha256,
        }

    def _insufficient_data(self, request, dataset):
        value = {
            "schema": dataset["schema"],
            "policy": dataset["policy"],
            "status": "insufficient_data",
            "provenance": self._provenance(request),
            "participants": [],
        }
        body = canonical_json(value)
        return C2DExportArtifact(
            body=body,
            checksum=hashlib.sha256(body).hexdigest(),
            dataset=value,
            pseudonym_key_id=self.pseudonym_key_id,
        )

    def _recording_feasibility(self, request, authority):
        profile = authority["profile"]["content"]
        limits = profile["limits"]
        dataset = authority["datasetView"]["content"]
        roster, enrollment_excluded = self._eligible_roster(authority, limits)
        study_state_count = len(roster) + enrollment_excluded
        empty_stats = {
            "study_state_count": study_state_count,
            "participant_count": 0,
            "excluded_participant_count": enrollment_excluded,
            "inspected_record_count": 0,
            "ineligible_record_count": 0,
            "unverified_record_count": 0,
            "recording_count": 0,
        }
        if len(roster) < limits["minimumParticipants"]:
            self._final_current_barrier(
                request, authority, limits, roster, ()
            )
            return self._insufficient_data(request, dataset), empty_stats

        try:
            documents = list(
                self._record_documents(
                    {owner for _user_id, owner, _enrollment in roster},
                    limits["maximumTotalRecordings"],
                )
            )
        except C2DExportError:
            raise
        except Exception as error:
            raise C2DExportError("record_source_unavailable", 503) from error
        documents.sort(
            key=lambda item: (item.get("created_by", ""), item.get("_id", ""))
        )
        by_owner = {}
        roster_owners = {owner for _user_id, owner, _enrollment in roster}
        for document in documents:
            owner = document.get("created_by")
            if not isinstance(owner, str) or owner not in roster_owners:
                raise C2DExportError("record_owner_invalid")
            by_owner.setdefault(owner, []).append(document)

        participants = []
        roster_commitments = []
        record_commitments = []
        ineligible_records = 0
        unverified_records = 0
        recording_count = 0
        record_excluded = 0
        selected_records = []
        for user_id, owner, enrollment in roster:
            subject_id = job_scoped_subject_id(
                self.pseudonym_secret,
                self.pseudonym_key_id,
                request["jobId"],
                user_id,
                "study",
            )
            candidates = []
            documents_by_id = {}
            capture_commitments = {}
            for document in by_owner.get(owner, []):
                record_id = document.get("_id")
                if not isinstance(record_id, str) or record_id in documents_by_id:
                    raise C2DExportError("record_set_invalid")
                documents_by_id[record_id] = document
                try:
                    verified = self.capture_time_verifier(deepcopy(document))
                except Exception as error:
                    raise C2DExportError(
                        "capture_verification_failed", 503
                    ) from error
                if verified is not True:
                    unverified_records += 1
                    continue
                capture_commitments[record_id] = content_sha256(
                    {
                        "schema": "brainstem.capture-verdict/v1",
                        "contentSha256": document.get("content_hash"),
                        "acceptedAtUtc": document.get("accepted_at_utc"),
                        "capturedAtUtc": document.get("captured_at_utc"),
                        "verified": True,
                    }
                )
                candidate = candidate_from_document(
                    document, capture_time_verified=True
                )
                if candidate is None:
                    ineligible_records += 1
                    continue
                candidates.append(candidate)

            recordings = []
            candidate_by_id = {item.record_id: item for item in candidates}
            for day_index, record_id in select_daily_records(
                candidates,
                self._selection_enrollment(enrollment),
                current_data_consent=True,
            ):
                current_document = self._current_record(
                    documents_by_id[record_id]
                )
                if current_document is None:
                    ineligible_records += 1
                    continue
                source = resting_rr_record(
                    self.upload_root, owner, current_document
                )
                candidate = candidate_by_id[record_id]
                if (
                    source is None
                    or source.captured_at_utc
                    != candidate.captured_at.strftime("%Y-%m-%dT%H:%M:%SZ")
                    or source.recording["durationSeconds"]
                    != int(candidate.duration_seconds)
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
                record_commitments.append(
                    {
                        "subjectId": subject_id,
                        "dayIndex": day_index,
                        "contentSha256": source.content_hash,
                        "captureEvidenceSha256": capture_commitments[record_id],
                    }
                )
                selected_records.append(
                    (owner, deepcopy(current_document), source)
                )
            if len(recordings) > limits["maximumRecordingsPerParticipant"]:
                raise C2DExportError("participant_recording_limit_exceeded", 413)
            if not recordings:
                record_excluded += 1
                continue
            roster_commitments.append(
                {
                    "subjectId": subject_id,
                    "enrollmentSha256": enrollment["enrollmentSha256"],
                }
            )
            participants.append(
                {"subjectId": subject_id, "recordings": recordings}
            )
            recording_count += len(recordings)

        if recording_count > limits["maximumTotalRecordings"]:
            raise C2DExportError("record_limit_exceeded", 413)
        if len(participants) < limits["minimumParticipants"]:
            stats = {
                "study_state_count": study_state_count,
                "participant_count": len(participants),
                "excluded_participant_count": (
                    enrollment_excluded + record_excluded
                ),
                "inspected_record_count": len(documents),
                "ineligible_record_count": ineligible_records,
                "unverified_record_count": unverified_records,
                "recording_count": recording_count,
            }
            self._final_current_barrier(
                request,
                authority,
                limits,
                roster,
                selected_records,
            )
            return self._insufficient_data(request, dataset), stats
        participants.sort(key=lambda item: item["subjectId"])
        roster_commitments.sort(key=lambda item: item["subjectId"])
        record_commitments.sort(
            key=lambda item: (item["subjectId"], item["dayIndex"])
        )
        value = {
            "schema": dataset["schema"],
            "policy": dataset["policy"],
            "status": "ready",
            "provenance": self._provenance(
                request,
                content_sha256(roster_commitments),
                content_sha256(record_commitments),
            ),
            "participants": participants,
        }
        body = canonical_json(value)
        if len(body) > limits["maximumInputBytes"]:
            raise C2DExportError("export_byte_limit_exceeded", 413)
        self._final_current_barrier(
            request,
            authority,
            limits,
            roster,
            selected_records,
        )
        return C2DExportArtifact(
            body=body,
            checksum=hashlib.sha256(body).hexdigest(),
            dataset=value,
            pseudonym_key_id=self.pseudonym_key_id,
        ), {
            "study_state_count": study_state_count,
            "participant_count": len(participants),
            "excluded_participant_count": enrollment_excluded + record_excluded,
            "inspected_record_count": len(documents),
            "ineligible_record_count": ineligible_records,
            "unverified_record_count": unverified_records,
            "recording_count": recording_count,
        }

    def build(self, request):
        self._configuration()
        authority = self._validate_request(request)
        adapters = {
            "brainstem.study-export.recording-feasibility.v1": (
                self._recording_feasibility
            )
        }
        adapter = adapters.get(request["datasetCapability"])
        if adapter is None:
            raise C2DExportError("dataset_capability_unavailable", 409)
        return adapter(request, authority)

    def _audit(self, request, outcome, stats, **extra):
        request_sha256 = (
            request.get("requestSha256") if isinstance(request, dict) else None
        )
        document = {
            "document_type": "brainstem_study_export_audit",
            "job_id_hash": hashlib.sha256(
                (
                    request.get("jobId", "<invalid>")
                    if isinstance(request, dict)
                    else "<invalid>"
                ).encode()
            ).hexdigest(),
            "pseudonym_key_id": self.pseudonym_key_id,
            "request_sha256": (
                request_sha256
                if isinstance(request_sha256, str)
                and SHA256.fullmatch(request_sha256)
                else None
            ),
            "outcome": outcome,
            "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            **stats,
            **extra,
        }
        self.audit_dao.save(
            "brainstem-study-audit:{}".format(uuid4().hex), document
        )

    def execute(self, request):
        empty = {
            "study_state_count": 0,
            "participant_count": 0,
            "excluded_participant_count": 0,
            "inspected_record_count": 0,
            "ineligible_record_count": 0,
            "unverified_record_count": 0,
            "recording_count": 0,
        }
        reservation = None
        job_id = request.get("jobId") if isinstance(request, dict) else None
        try:
            self._configuration()
            if (
                not isinstance(request, dict)
                or set(request) != REQUEST_FIELDS
                or not isinstance(job_id, str)
                or not JOB_ID_PATTERN.fullmatch(job_id)
                or request.get("requestSha256") != _request_sha256(request)
            ):
                raise C2DExportError("materialization_request_invalid", 400)
            reservation = reserve_export_job(
                self.audit_dao,
                "study",
                job_id,
                self.pseudonym_key_id,
                request["requestSha256"],
            )
            artifact, stats = self.build(request)
            outcome = artifact.dataset["status"]
            self._audit(
                request,
                outcome,
                stats,
                byte_count=len(artifact.body),
                checksum=artifact.checksum,
            )
            finish_export_job(
                self.audit_dao,
                "study",
                job_id,
                reservation["lease"],
                "completed",
                artifact.checksum,
            )
            return artifact
        except C2DExportError as error:
            try:
                if reservation and reservation.get("state") == "reserved":
                    finish_export_job(
                        self.audit_dao,
                        "study",
                        job_id,
                        reservation["lease"],
                        "failed",
                    )
                self._audit(request, "rejected", empty, reason=error.code)
            except Exception as audit_error:
                raise C2DExportError("audit_failed", 503) from audit_error
            raise
        except Exception as error:
            try:
                if reservation and reservation.get("state") == "reserved":
                    finish_export_job(
                        self.audit_dao,
                        "study",
                        job_id,
                        reservation["lease"],
                        "failed",
                    )
                self._audit(request, "failed", empty, reason="internal_error")
            except Exception as audit_error:
                raise C2DExportError("audit_failed", 503) from audit_error
            raise C2DExportError("export_failed", 500) from error
