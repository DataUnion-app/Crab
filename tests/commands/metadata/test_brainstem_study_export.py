from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json

import pytest

from commands.dataunions.brainstem.c2d_export import C2DExportError
from commands.dataunions.brainstem.generic_study_service import (
    GenericStudyServiceError,
)
from commands.dataunions.brainstem.record_contract import parse_record
from commands.dataunions.brainstem.study_activation import release_binding
from commands.dataunions.brainstem.study_export import BrainstemStudyExporter
from commands.dataunions.brainstem.study_operations import StudyOperationsError
from commands.dataunions.brainstem.study_registry import (
    DEFAULT_STUDY_REGISTRY,
    RECORDING_FEASIBILITY_ID,
)
from commands.dataunions.studies.registry import content_sha256


JOB_A = "a" * 64
JOB_B = "b" * 64
PROPOSAL_ID = "study_abcd"
PERMIT_ID = "permit_" + "1" * 32
PERMIT_SHA256 = "2" * 64
STATE_SHA256 = "3" * 64
START = datetime(2026, 8, 2, tzinfo=timezone.utc)


class QueryDao:
    def __init__(self, values=()):
        self.values = list(values)
        self.saved = []
        self.queries = []
        self.iter_error = None
        self.get_error = None
        self.current_values = None

    def iter_query(self, query, batch_size):
        assert batch_size == 500
        self.queries.append(deepcopy(query))
        if self.iter_error is not None:
            raise self.iter_error
        owners = set(query["selector"]["created_by"]["$in"])
        yield from deepcopy(
            [item for item in self.values if item.get("created_by") in owners]
        )

    def save(self, doc_id, value):
        self.saved = [
            (saved_id, saved_value)
            for saved_id, saved_value in self.saved
            if saved_id != doc_id
        ]
        self.saved.append((doc_id, deepcopy(value)))

    def get_if_exists(self, doc_id):
        if self.get_error is not None:
            raise self.get_error
        values = self.values if self.current_values is None else self.current_values
        for value in values:
            if value.get("_id") == doc_id:
                return True, deepcopy(value)
        for saved_id, value in self.saved:
            if saved_id == doc_id:
                return True, deepcopy(value)
        return False, None

    def mutate_doc(self, doc_id, mutator):
        exists, value = self.get_if_exists(doc_id)
        assert exists
        updated = mutator(value)
        if updated is None:
            return value
        self.save(doc_id, updated)
        return deepcopy(updated)


class StudyDao:
    def __init__(self, states):
        self.states = states
        self.calls = []
        self.error = None

    def materialization_states(self, offering_id, limit):
        self.calls.append((offering_id, limit))
        assert offering_id == RECORDING_FEASIBILITY_ID
        assert limit == 10001
        if self.error is not None:
            raise self.error
        return deepcopy(self.states)


class UsersDao:
    def __init__(self, users):
        self.users = users
        self.error = None

    def get_doc_by_id(self, user_id):
        if self.error is not None:
            raise self.error
        return deepcopy(self.users[user_id])


class Activation:
    def __init__(self, permit):
        self.permit = permit
        self.calls = []

    def load_verified_permit(self, proposal_id, permit_id):
        self.calls.append((proposal_id, permit_id))
        assert proposal_id == PROPOSAL_ID
        assert permit_id == PERMIT_ID
        return deepcopy(self.permit)


class Operations:
    def __init__(self, state):
        self.state = state
        self.calls = []
        self.authority_current = True

    def load_verified_status(self, proposal_id, permit_id):
        self.calls.append(("status", proposal_id, permit_id))
        return {"state": deepcopy(self.state), "events": [{"verified": True}]}

    def load_verified_operation(self, proposal_id, permit_id, capability):
        self.calls.append(("operation", proposal_id, permit_id, capability))
        if not self.authority_current:
            raise StudyOperationsError("study_authority_invalid", 409)
        if (
            self.state["lifecycleState"] != "active"
            or self.state["disposition"] != "current"
            or capability != "materialization"
        ):
            raise StudyOperationsError("study_operation_not_allowed", 409)
        return self.load_verified_status(proposal_id, permit_id)


class Enrollments:
    def __init__(self, states):
        self.states = states
        self.calls = []
        self.error = None

    def load_verified_enrollment(
        self, user_id, offering_id, *, user
    ):
        self.calls.append((user_id, offering_id))
        if self.error is not None:
            raise self.error
        state = next(
            item for item in self.states if item.get("user_id") == user_id
        )
        private = state["offerings"][offering_id]
        enrollment = private["enrollment"]
        if (
            private.get("authority") != "verified"
            or enrollment.get("state") != "active"
            or user.get("is_access_blocked") is True
            or user.get("usage_flag") != "ACCEPTED"
            or user.get("guidelines_acceptance_flag") != "ACCEPTED"
        ):
            raise GenericStudyServiceError("enrollment_evidence_invalid", 409)
        return deepcopy(enrollment)


def enrollment(user_id, release, state="active"):
    value = {
        "offeringId": release["offeringId"],
        "releaseVersion": release["releaseVersion"],
        "releaseSha256": release["releaseSha256"],
        "proposalId": PROPOSAL_ID,
        "permitId": PERMIT_ID,
        "taskPlan": deepcopy(release["taskPlan"]),
        "state": state,
        "startsAt": int(START.timestamp()),
        "endsAt": int((START + timedelta(days=14)).timestamp()),
        "enrollmentSha256": hashlib.sha256(user_id.encode()).hexdigest(),
    }
    return value


def participant_state(user_id, release, state="active"):
    return {
        "user_id": user_id,
        "offerings": {
            release["offeringId"]: {
                "authority": "verified",
                "enrollment": enrollment(user_id, release, state),
            }
        },
    }


def record(upload_root, owner, record_id, day, fractional=False):
    captured = START + timedelta(days=day, minutes=1)
    source = {
        "schemaVersion": "1.0",
        "type": "rest",
        "timestamp": captured.strftime("%Y-%m-%d_%H%M%S"),
        "captureTime": {
            "basis": "rfc3339-utc",
            "startedAt": captured.strftime("%Y-%m-%dT%H:%M:%SZ"),
        },
        "datasource": {
            "sensor": {
                "name": "GENERATED-STUDY-SENSOR",
                "id": "GENERATED-STUDY-DEVICE",
                "payloads": {
                    "hbr_rr": {
                        "dataType": "hbr_rr",
                        "format": "csv",
                        "data": ";".join(
                            "{},60,800".format(
                                second
                                + (0.2 if fractional and second == 299 else 0)
                            )
                            for second in range(300)
                        )
                        + (",249,invalid" if fractional else ""),
                    }
                },
            }
        },
    }
    summary = parse_record(source)
    path = upload_root / owner / "{}.json".format(record_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(source), encoding="utf-8")
    canonical = json.dumps(source, sort_keys=True, separators=(",", ":")).encode()
    return {
        "_id": record_id,
        "created_by": owner,
        "file_path": str(path),
        "content_hash": hashlib.sha256(canonical).hexdigest(),
        "file_type": "record",
        "record_contract_version": "brainstem-record-v1",
        "record_type": "rest",
        "recognized_payloads": ["hbr_rr"],
        "duration": summary.duration,
        "valid_rr_intervals": summary.valid_rr_intervals,
        "accepted_at_utc": (captured + timedelta(minutes=5)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        ),
        "captured_at_utc": captured.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def fixture(tmp_path, participant_count=22):
    release = DEFAULT_STUDY_REGISTRY.release(RECORDING_FEASIBILITY_ID)
    profile = DEFAULT_STUDY_REGISTRY.activation_profile(
        release["offeringId"], release["releaseVersion"], release["releaseSha256"]
    )
    permit = {
        "permitId": PERMIT_ID,
        "permitSha256": PERMIT_SHA256,
        "bundle": {
            "release": release_binding(release),
            "activationProfile": deepcopy(profile),
        },
    }
    operations_state = {
        "proposalId": PROPOSAL_ID,
        "permitId": PERMIT_ID,
        "permitSha256": PERMIT_SHA256,
        "offeringId": release["offeringId"],
        "releaseVersion": release["releaseVersion"],
        "releaseSha256": release["releaseSha256"],
        "taskPlan": deepcopy(release["taskPlan"]),
        "lifecycleState": "active",
        "disposition": "current",
        "stateSha256": STATE_SHA256,
    }
    users = {}
    states = []
    records = []
    raw_identifiers = []
    for index in range(participant_count):
        user_id = "GENERATED-USER-{}".format(index)
        owner = "GENERATED-WALLET-{}".format(index)
        users[user_id] = {
            "_id": user_id,
            "public_address": owner,
            "usage_flag": "ACCEPTED",
            "guidelines_acceptance_flag": "ACCEPTED",
            "is_access_blocked": False,
        }
        states.append(participant_state(user_id, release))
        record_id = "GENERATED-RECORD-{}".format(index)
        records.append(record(tmp_path, owner, record_id, 0))
        raw_identifiers.extend((user_id, owner, record_id))
    metadata = QueryDao(records)
    audit = QueryDao()
    activation = Activation(permit)
    operations = Operations(operations_state)
    enrollments = Enrollments(states)
    users_dao = UsersDao(users)
    study_dao = StudyDao(states)
    exporter = BrainstemStudyExporter(
        metadata,
        users_dao,
        study_dao,
        audit,
        tmp_path,
        "generated-secret-" + "s" * 32,
        "generated-v1",
        lambda document: document["_id"] != "never",
        activation_service=activation,
        operations_service=operations,
        enrollment_service=enrollments,
    )
    return {
        "exporter": exporter,
        "users": users,
        "states": states,
        "metadata": metadata,
        "users_dao": users_dao,
        "study_dao": study_dao,
        "audit": audit,
        "activation": activation,
        "operations": operations,
        "enrollments": enrollments,
        "identifiers": raw_identifiers,
        "release": release,
        "profile": profile,
    }


def request(current, job_id=JOB_A):
    return current["exporter"].create_request(job_id, PROPOSAL_ID, PERMIT_ID)


def test_materialization_is_canonical_private_purpose_bound_and_job_scoped(tmp_path):
    current = fixture(tmp_path)
    first_request = request(current)
    first = current["exporter"].execute(first_request)
    other = current["exporter"].execute(request(current, JOB_B))

    assert first.dataset["status"] == "ready"
    assert first.body == json.dumps(
        first.dataset, sort_keys=True, separators=(",", ":")
    ).encode()
    assert len(first.dataset["participants"]) == 22
    assert [item["subjectId"] for item in first.dataset["participants"]] != [
        item["subjectId"] for item in other.dataset["participants"]
    ]
    assert first.dataset["provenance"]["algorithmImageDigest"] == current[
        "profile"
    ]["content"]["algorithmImageDigest"]
    assert first_request["approvedManifestSha256"] == current["profile"][
        "content"
    ]["approvedManifestSha256"]
    assert first_request["referenceSha256"] == current["profile"]["content"][
        "referenceSha256"
    ]
    assert current["profile"]["content"]["environment"] == "generated-local"
    assert current["profile"]["content"]["dataMode"] == "generated_only"
    assert DEFAULT_STUDY_REGISTRY.artifact(current["release"]["survey"])[
        "content"
    ]["clinicalVerification"] is False
    with pytest.raises(C2DExportError, match="job_id_completed"):
        current["exporter"].execute(first_request)
    exposed = first.body.decode() + json.dumps(current["audit"].saved)
    assert all(identifier not in exposed for identifier in current["identifiers"])
    assert JOB_A not in exposed
    expected_calls = sorted(
        (
            "GENERATED-USER-{}".format(index),
            RECORDING_FEASIBILITY_ID,
        )
        for index in range(22)
    )
    assert current["enrollments"].calls == expected_calls * 4


def test_transient_failure_retries_exact_same_bound_request(tmp_path):
    current = fixture(tmp_path)
    materialization_request = request(current)
    build = current["exporter"].build
    attempts = [0]

    def flaky(value):
        attempts[0] += 1
        if attempts[0] == 1:
            raise C2DExportError("temporary_failure", 503)
        return build(value)

    current["exporter"].build = flaky
    with pytest.raises(C2DExportError, match="temporary_failure"):
        current["exporter"].execute(materialization_request)
    assert current["exporter"].execute(materialization_request).dataset[
        "status"
    ] == "ready"


def test_nineteen_is_one_canonical_indistinguishable_insufficient_artifact(tmp_path):
    nineteen = fixture(tmp_path / "nineteen", participant_count=19)
    excluded = fixture(tmp_path / "excluded", participant_count=22)
    for index in range(3):
        excluded["users"]["GENERATED-USER-{}".format(index)][
            "usage_flag"
        ] = "REJECTED"
    calls = [0]
    excluded["exporter"].capture_time_verifier = lambda _document: calls.__setitem__(
        0, calls[0] + 1
    )

    first = nineteen["exporter"].execute(request(nineteen))
    second = excluded["exporter"].execute(request(excluded))
    assert first.dataset["status"] == "insufficient_data"
    assert first.body == second.body
    assert first.dataset["participants"] == []
    assert first.dataset["provenance"]["rosterSha256"] is None
    assert first.dataset["provenance"]["recordSetSha256"] is None
    assert calls == [0]


def test_post_record_floor_suppresses_twenty_enrolled_with_nineteen_or_zero_data(
    tmp_path,
):
    twenty_records = fixture(tmp_path / "twenty-records", participant_count=20)
    nineteen_records = fixture(tmp_path / "nineteen-records", participant_count=20)
    nineteen_records["metadata"].values.pop()
    zero_records = fixture(tmp_path / "zero-records", participant_count=20)
    zero_records["exporter"].capture_time_verifier = lambda _document: False

    complete = twenty_records["exporter"].execute(request(twenty_records))
    first = nineteen_records["exporter"].execute(request(nineteen_records))
    second = zero_records["exporter"].execute(request(zero_records))
    assert complete.dataset["status"] == "ready"
    assert len(complete.dataset["participants"]) == 20
    assert first.dataset["status"] == "insufficient_data"
    assert first.body == second.body
    assert first.dataset["participants"] == []


@pytest.mark.parametrize(
    ("mutation",),
    (
        ("withdrawn",),
        ("renewal_required",),
        ("deleted",),
        ("consent",),
        ("access",),
        ("ticket",),
    ),
)
def test_non_authoritative_participant_states_never_enter_materialization(
    tmp_path, mutation
):
    current = fixture(tmp_path)
    for index in range(3):
        user_id = "GENERATED-USER-{}".format(index)
        private = current["states"][index]["offerings"][
            RECORDING_FEASIBILITY_ID
        ]
        if mutation in {"withdrawn", "renewal_required", "deleted"}:
            private["enrollment"]["state"] = mutation
        elif mutation == "consent":
            current["users"][user_id]["usage_flag"] = "REJECTED"
        elif mutation == "access":
            current["users"][user_id]["is_access_blocked"] = True
        else:
            private["authority"] = "forged-ticket"
    artifact = current["exporter"].execute(request(current))
    assert artifact.dataset["status"] == "insufficient_data"
    assert artifact.dataset["participants"] == []


@pytest.mark.parametrize(
    "field",
    (
        "operationStateSha256",
        "releaseSha256",
        "taskPlanSha256",
        "activationProfileSha256",
        "algorithmImageDigest",
        "approvedManifestSha256",
        "referenceSha256",
    ),
)
def test_changed_state_profile_image_manifest_or_reference_rejects_bound_request(
    tmp_path, field
):
    current = fixture(tmp_path)
    value = request(current)
    if field == "algorithmImageDigest":
        value[field] = "sha256:" + "f" * 64
    else:
        value[field] = "f" * 64
    value["requestSha256"] = content_sha256(
        {key: item for key, item in value.items() if key != "requestSha256"}
    )
    with pytest.raises(C2DExportError, match="materialization_request_stale"):
        current["exporter"].execute(value)


def test_lifecycle_change_after_request_creation_fails_closed(tmp_path):
    current = fixture(tmp_path)
    value = request(current)
    current["operations"].state["lifecycleState"] = "paused"
    current["operations"].state["stateSha256"] = "f" * 64
    with pytest.raises(C2DExportError, match="study_not_active"):
        current["exporter"].execute(value)


def test_finalized_authority_change_after_request_creation_fails_closed(tmp_path):
    current = fixture(tmp_path)
    value = request(current)
    current["operations"].authority_current = False
    with pytest.raises(C2DExportError, match="study_authority_invalid") as denied:
        current["exporter"].execute(value)
    assert denied.value.status_code == 409


@pytest.mark.parametrize(
    "owner",
    ("permit", "operation", "release", "task_plan", "image", "manifest", "reference"),
)
def test_current_bound_authority_is_reloaded_at_job_time(tmp_path, owner):
    current = fixture(tmp_path)
    value = request(current)
    if owner == "permit":
        current["activation"].permit["permitSha256"] = "f" * 64
    elif owner == "operation":
        current["operations"].state["stateSha256"] = "f" * 64
    elif owner == "release":
        current["operations"].state["releaseSha256"] = "f" * 64
    elif owner == "task_plan":
        current["operations"].state["taskPlan"] = {
            **current["operations"].state["taskPlan"],
            "sha256": "f" * 64,
        }
    else:
        field = {
            "image": "algorithmImageDigest",
            "manifest": "approvedManifestSha256",
            "reference": "referenceSha256",
        }[owner]
        replacement = "sha256:" + "f" * 64 if owner == "image" else "f" * 64
        current["activation"].permit["bundle"]["activationProfile"][
            "content"
        ][field] = replacement

    with pytest.raises(C2DExportError) as denied:
        current["exporter"].execute(value)
    assert denied.value.status_code == 409


@pytest.mark.parametrize(
    ("mutation", "code"),
    (
        ("pause", "study_not_active"),
        ("finalized_owner", "study_authority_invalid"),
        ("state_sha", "materialization_request_stale"),
    ),
)
def test_final_barrier_rejects_authority_mutation_during_record_work(
    tmp_path, mutation, code
):
    current = fixture(tmp_path, participant_count=20)
    changed = [False]

    def mutate_authority(_document):
        if not changed[0]:
            changed[0] = True
            if mutation == "pause":
                current["operations"].state["lifecycleState"] = "paused"
                current["operations"].state["stateSha256"] = "f" * 64
            elif mutation == "finalized_owner":
                current["operations"].authority_current = False
            else:
                current["operations"].state["stateSha256"] = "f" * 64
        return True

    current["exporter"].capture_time_verifier = mutate_authority
    with pytest.raises(C2DExportError, match=code) as denied:
        current["exporter"].execute(request(current))
    assert denied.value.status_code == 409
    exposed = json.dumps(current["audit"].saved)
    assert all(identifier not in exposed for identifier in current["identifiers"])
    assert JOB_A not in exposed


def test_final_barrier_uses_the_same_snapshot_that_authorized_materialization(
    tmp_path,
):
    current = fixture(tmp_path, participant_count=20)
    value = request(current)
    original = current["operations"].load_verified_operation
    calls = [0]

    def mutate_during_final_operation_load(proposal_id, permit_id, capability):
        calls[0] += 1
        if calls[0] == 2:
            current["operations"].state["stateSha256"] = "f" * 64
        return original(proposal_id, permit_id, capability)

    current["operations"].load_verified_operation = (
        mutate_during_final_operation_load
    )
    with pytest.raises(
        C2DExportError, match="materialization_request_stale"
    ) as denied:
        current["exporter"].execute(value)
    assert denied.value.status_code == 409
    exposed = json.dumps(current["audit"].saved)
    assert all(identifier not in exposed for identifier in current["identifiers"])
    assert JOB_A not in exposed


@pytest.mark.parametrize(
    "mutation",
    (
        "withdrawn",
        "deleted",
        "renewal_required",
        "renewed",
        "consent",
        "access",
    ),
)
def test_final_barrier_rejects_participant_evidence_mutation_during_record_work(
    tmp_path, mutation
):
    current = fixture(tmp_path, participant_count=20)
    changed = [False]

    def mutate_participant(_document):
        if not changed[0]:
            changed[0] = True
            user_id = "GENERATED-USER-0"
            enrollment = current["states"][0]["offerings"][
                RECORDING_FEASIBILITY_ID
            ]["enrollment"]
            if mutation in {"withdrawn", "deleted", "renewal_required"}:
                enrollment["state"] = mutation
            elif mutation == "renewed":
                enrollment["enrollmentSha256"] = "f" * 64
            elif mutation == "consent":
                current["users"][user_id]["usage_flag"] = "REJECTED"
            else:
                current["users"][user_id]["is_access_blocked"] = True
        return True

    current["exporter"].capture_time_verifier = mutate_participant
    with pytest.raises(
        C2DExportError, match="materialization_source_stale"
    ) as denied:
        current["exporter"].execute(request(current))
    assert denied.value.status_code == 409
    exposed = json.dumps(current["audit"].saved)
    assert all(identifier not in exposed for identifier in current["identifiers"])
    assert JOB_A not in exposed


@pytest.mark.parametrize(
    ("source", "code"),
    (
        ("participant", "participant_source_unavailable"),
        ("enrollment", "enrollment_source_unavailable"),
        ("study_state", "study_state_unavailable"),
        ("record_query", "record_source_unavailable"),
        ("record_lookup", "record_source_unavailable"),
    ),
)
def test_storage_outages_fail_closed_instead_of_becoming_insufficient_data(
    tmp_path, source, code
):
    current = fixture(tmp_path, participant_count=20)
    if source == "participant":
        current["users_dao"].error = RuntimeError("user store unavailable")
    elif source == "enrollment":
        current["enrollments"].error = RuntimeError(
            "enrollment store unavailable"
        )
    elif source == "study_state":
        current["study_dao"].error = RuntimeError("study store unavailable")
    elif source == "record_query":
        current["metadata"].iter_error = RuntimeError(
            "record store unavailable"
        )
    else:
        current["metadata"].get_error = RuntimeError(
            "record store unavailable"
        )

    with pytest.raises(C2DExportError, match=code) as denied:
        current["exporter"].execute(request(current))
    assert denied.value.status_code == 503
    audits = [
        value
        for _doc_id, value in current["audit"].saved
        if value.get("document_type") == "brainstem_study_export_audit"
    ]
    assert audits[-1]["outcome"] == "rejected"
    assert audits[-1]["reason"] == code


def test_typed_participant_ineligibility_still_uses_disclosure_suppression(
    tmp_path,
):
    current = fixture(tmp_path, participant_count=20)
    for index in range(2):
        current["states"][index]["offerings"][RECORDING_FEASIBILITY_ID][
            "enrollment"
        ]["state"] = "withdrawn"
    artifact = current["exporter"].execute(request(current))
    assert artifact.dataset["status"] == "insufficient_data"
    assert artifact.dataset["participants"] == []


def test_stale_roster_discovery_cannot_override_current_withdrawal(tmp_path):
    current = fixture(tmp_path, participant_count=20)
    current["study_dao"].states = deepcopy(current["states"])
    current["states"][0]["offerings"][RECORDING_FEASIBILITY_ID]["enrollment"][
        "state"
    ] = "withdrawn"

    artifact = current["exporter"].execute(request(current))
    assert artifact.dataset["status"] == "insufficient_data"
    assert artifact.dataset["participants"] == []


def test_deleted_record_after_discovery_is_removed_before_disclosure_floor(
    tmp_path,
):
    current = fixture(tmp_path, participant_count=20)
    current["metadata"].current_values = deepcopy(current["metadata"].values[1:])

    artifact = current["exporter"].execute(request(current))
    assert artifact.dataset["status"] == "insufficient_data"
    assert artifact.dataset["participants"] == []


def test_changed_record_after_discovery_fails_closed(tmp_path):
    current = fixture(tmp_path, participant_count=20)
    current["metadata"].current_values = deepcopy(current["metadata"].values)
    current["metadata"].current_values[0]["content_hash"] = "f" * 64

    with pytest.raises(C2DExportError, match="record_source_changed") as denied:
        current["exporter"].execute(request(current))
    assert denied.value.status_code == 409


@pytest.mark.parametrize("mutation", ("deleted", "metadata", "source"))
def test_final_barrier_rejects_selected_record_mutation_after_initial_load(
    tmp_path, mutation
):
    current = fixture(tmp_path, participant_count=20)
    metadata = current["metadata"]
    original_get = metadata.get_if_exists
    calls = [0]

    def mutate_before_final_lookup(doc_id):
        calls[0] += 1
        if calls[0] == 21:
            metadata.current_values = deepcopy(metadata.values)
            selected = next(
                item for item in metadata.current_values if item["_id"] == doc_id
            )
            if mutation == "deleted":
                metadata.current_values.remove(selected)
            elif mutation == "metadata":
                selected["content_hash"] = "f" * 64
            else:
                path = selected["file_path"]
                with open(path, "r+", encoding="utf-8") as source:
                    content = source.read()
                    source.seek(0)
                    source.write(content.replace(",60,800", ",60,801", 1))
                    source.truncate()
        return original_get(doc_id)

    metadata.get_if_exists = mutate_before_final_lookup
    with pytest.raises(C2DExportError) as denied:
        current["exporter"].execute(request(current))
    assert denied.value.status_code == 409
    assert denied.value.code in {
        "record_source_changed",
        "materialization_source_stale",
    }
    exposed = json.dumps(current["audit"].saved)
    assert all(identifier not in exposed for identifier in current["identifiers"])
    assert JOB_A not in exposed


@pytest.mark.parametrize(
    "injected",
    (
        {"selector": {"all": True}},
        {"url": "https://participant.example"},
        {"roster": ["participant-one"]},
        {"fields": ["raw"]},
        {"records": [{"rr": [800]}]},
        {"command": "export all"},
    ),
)
def test_request_rejects_caller_selection_data_and_commands(tmp_path, injected):
    current = fixture(tmp_path)
    value = {**request(current), **injected}
    with pytest.raises(C2DExportError, match="materialization_request_invalid"):
        current["exporter"].execute(value)
    with pytest.raises(C2DExportError, match="materialization_request_invalid"):
        current["exporter"].execute(JOB_A)


def test_cross_request_job_reuse_is_rejected_and_cross_job_pseudonyms_change(tmp_path):
    current = fixture(tmp_path)
    first = request(current)
    current["exporter"].execute(first)
    changed = request(current, JOB_A)
    changed["referenceSha256"] = "f" * 64
    changed["requestSha256"] = content_sha256(
        {key: item for key, item in changed.items() if key != "requestSha256"}
    )
    with pytest.raises(C2DExportError, match="job_id_reused"):
        current["exporter"].execute(changed)


def test_source_owned_window_capture_and_provenance_exclude_unverified_records(
    tmp_path,
):
    current = fixture(tmp_path)
    first_record = current["metadata"].values[0]
    current["exporter"].capture_time_verifier = (
        lambda document: document["_id"] != first_record["_id"]
    )
    artifact = current["exporter"].execute(request(current))
    assert artifact.dataset["status"] == "ready"
    assert len(artifact.dataset["participants"]) == 21
    assert sum(
        len(item["recordings"]) for item in artifact.dataset["participants"]
    ) == 21
    assert artifact.dataset["provenance"]["rosterSha256"]
    assert artifact.dataset["provenance"]["recordSetSha256"]
    assert first_record["_id"] not in artifact.body.decode()
    query = current["metadata"].queries[0]
    assert set(query["fields"]) == {
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
    }
    assert set(query["selector"]) == {
        "file_type",
        "record_contract_version",
        "record_type",
        "recognized_payloads",
        "created_by",
    }


def test_source_owned_selector_excludes_pre_window_and_end_boundary_records(
    tmp_path,
):
    current = fixture(tmp_path, participant_count=20)
    owner = current["metadata"].values[0]["created_by"]
    before_id = "GENERATED-BEFORE-WINDOW"
    end_id = "GENERATED-END-BOUNDARY"
    current["metadata"].values.extend(
        (
            record(tmp_path, owner, before_id, -1),
            record(tmp_path, owner, end_id, 14),
        )
    )
    artifact = current["exporter"].execute(request(current))
    assert artifact.dataset["status"] == "ready"
    assert len(artifact.dataset["participants"]) == 20
    assert before_id not in artifact.body.decode()
    assert end_id not in artifact.body.decode()


def test_source_hash_and_total_record_limits_fail_closed(tmp_path):
    current = fixture(tmp_path / "hash")
    current["metadata"].values[0]["content_hash"] = "f" * 64
    with pytest.raises(C2DExportError, match="source_hash_mismatch"):
        current["exporter"].execute(request(current))

    overflow = fixture(tmp_path / "overflow")
    template = overflow["metadata"].values[0]
    overflow["metadata"].values = [
        {**template, "_id": "record-{}".format(index)}
        for index in range(1401)
    ]
    with pytest.raises(C2DExportError, match="record_limit_exceeded"):
        overflow["exporter"].execute(request(overflow))


def test_profile_participant_limit_is_enforced_after_verified_filter(tmp_path):
    current = fixture(tmp_path, participant_count=101)
    with pytest.raises(C2DExportError, match="participant_limit_exceeded"):
        current["exporter"].execute(request(current))


def test_fractional_duration_and_invalid_rr_values_converge_on_legacy_adapter(
    tmp_path,
):
    current = fixture(tmp_path)
    owner = current["metadata"].values[0]["created_by"]
    current["metadata"].values[0] = record(
        tmp_path,
        owner,
        current["metadata"].values[0]["_id"],
        0,
        fractional=True,
    )
    artifact = current["exporter"].execute(request(current))
    recordings = [
        recording
        for participant in artifact.dataset["participants"]
        for recording in participant["recordings"]
    ]
    assert any(item["durationSeconds"] == 300 for item in recordings)
    assert all(len(item["rrIntervalsMs"]) == 300 for item in recordings)
