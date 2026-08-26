from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import threading

import pytest
from eth_account import Account
from eth_account.messages import encode_defunct

from commands.dataunions.brainstem import personal_insight, record_export
from commands.dataunions.brainstem.personal_insight import (
    BrainstemPersonalInsightService,
    PersonalInsightError,
)
from dao.personal_insight_dao import PersonalInsightStateError


ORIGIN = "http://127.0.0.1:3000"
PRIVATE_KEY = "0x" + "31" * 32
ACCOUNT = Account.from_key(PRIVATE_KEY)
OTHER_ACCOUNT = Account.from_key("0x" + "32" * 32)
JOB_A = "a" * 64
JOB_B = "b" * 64
RUN_A = "c" * 32
RUN_B = "d" * 32
DIGEST = "sha256:" + "2" * 64
RESULT_SHA256 = "e" * 64


def generated_record(timestamp, interval=800, valid=True, canary="device-canary"):
    rows = ";".join(
        "{},60,{}".format(second, interval if valid else "not-a-number")
        for second in range(300)
    )
    return {
        "schemaVersion": "1.0",
        "type": "rest",
        "timestamp": timestamp,
        "metadata": {
            "gender": "generated",
            "year": 1990,
            "region": "generated",
        },
        "datasource": {
            "sensor": {
                "name": "generated",
                "id": canary,
                "payloads": {
                    "hbr_rr": {
                        "dataType": "hbr_rr",
                        "format": "csv",
                        "data": rows,
                    }
                },
            }
        },
    }


def generated_sleep_record(timestamp, interval=900, canary="device-canary"):
    record = generated_record(timestamp, interval, canary=canary)
    record["type"] = "sleep"
    record["datasource"]["sensor"]["payloads"]["hbr_rr"]["data"] = ";".join(
        "{},60,{}".format(second, interval) for second in range(18_001)
    )
    return record


class MemoryAuth:
    def __init__(self, user):
        self.user = user
        self.valid = True

    def authenticate(self, token, origin):
        if not self.valid or token != "participant-session" or origin != ORIGIN:
            raise PersonalInsightError("participant_session_invalid", 401)
        return "session-id", {"scope": "participant:self:status:read"}, deepcopy(
            self.user
        )


class MemoryUsers:
    def __init__(self, users):
        self.users = users

    def get_doc_by_id(self, user_id):
        if user_id not in self.users:
            raise KeyError(user_id)
        return deepcopy(self.users[user_id])


class MemoryMetadata:
    def __init__(self, documents):
        self.documents = {document["_id"]: document for document in documents}

    def iter_query(self, query, batch_size):
        assert batch_size == 500
        owner = query["selector"]["created_by"]
        for document in list(self.documents.values()):
            if document.get("created_by") == owner:
                yield deepcopy(document)

    def get_doc_by_id(self, document_id):
        if document_id not in self.documents:
            raise KeyError(document_id)
        return deepcopy(self.documents[document_id])


class MemoryPersonalDao:
    def __init__(self):
        self.challenges = {}
        self.grants = {}
        self.lock = threading.Lock()

    def create_or_get_challenge(self, slot, data, now):
        with self.lock:
            current = self.challenges.get(slot)
            if (
                current
                and current["consumed_at"] is None
                and current["expires_at"] > now
            ):
                return deepcopy(current)
            self.challenges[slot] = deepcopy(data)
            return deepcopy(data)

    def get_challenge(self, slot):
        with self.lock:
            if slot not in self.challenges:
                raise PersonalInsightStateError("Challenge unavailable")
            return deepcopy(self.challenges[slot])

    def consume_challenge(self, slot, challenge_id, now):
        with self.lock:
            challenge = self.challenges[slot]
            if challenge["challenge_id"] != challenge_id:
                raise PersonalInsightStateError("Challenge unavailable")
            if challenge["consumed_at"] is not None:
                raise PersonalInsightStateError("Challenge already used")
            if challenge["expires_at"] <= now:
                raise PersonalInsightStateError("Challenge expired")
            message = challenge.pop("message")
            address = challenge.pop("address")
            challenge["message_sha256"] = hashlib.sha256(
                message.encode()
            ).hexdigest()
            challenge["address_sha256"] = hashlib.sha256(
                address.encode()
            ).hexdigest()
            challenge["consumed_at"] = now

    def save_grant(self, grant_id, data):
        with self.lock:
            if grant_id in self.grants:
                raise RuntimeError("conflict")
            document = deepcopy(data)
            document["_id"] = "personal_insight_grant:" + grant_id
            self.grants[grant_id] = document

    def get_grant(self, grant_id):
        with self.lock:
            if grant_id not in self.grants:
                raise PersonalInsightStateError("Grant unavailable")
            return deepcopy(self.grants[grant_id])

    def claim_grant(
        self, grant_id, token_hash, job_hash, run_hash, history_id, now
    ):
        with self.lock:
            grant = self.grants[grant_id]
            if grant["token_sha256"] != token_hash:
                raise PersonalInsightStateError("Grant unavailable")
            if grant["expires_at"] <= now:
                raise PersonalInsightStateError("Grant expired")
            if grant["job_id_sha256"] is not None:
                if (
                    grant["job_id_sha256"] != job_hash
                    or grant["run_id_sha256"] != run_hash
                    or grant["history_id"] != history_id
                ):
                    raise PersonalInsightStateError("Grant already bound")
                if grant["state"] != "claimed":
                    raise PersonalInsightStateError("Grant already used")
                return deepcopy(grant)
            if grant["state"] != "approved":
                raise PersonalInsightStateError("Grant unavailable")
            grant["state"] = "claimed"
            grant["job_id_sha256"] = job_hash
            grant["run_id_sha256"] = run_hash
            grant["history_id"] = history_id
            grant["claimed_at"] = now
            return deepcopy(grant)

    def list_history(self, user_id, origin, limit):
        with self.lock:
            matches = [
                deepcopy(grant)
                for grant in self.grants.values()
                if grant.get("document_type")
                == "brainstem_personal_insight_grant"
                and grant.get("user_id") == user_id
                and grant.get("origin") == origin
                and isinstance(grant.get("history_id"), str)
            ]
            return matches[:limit]

    def get_history(self, history_id):
        with self.lock:
            matches = [
                grant
                for grant in self.grants.values()
                if grant.get("history_id") == history_id
                and grant.get("document_type")
                == "brainstem_personal_insight_grant"
            ]
            if len(matches) != 1:
                raise PersonalInsightStateError("History unavailable")
            return deepcopy(matches[0])

    def begin_fetch(self, grant_id, token_hash, job_hash, now):
        with self.lock:
            grant = self.grants[grant_id]
            if grant["token_sha256"] != token_hash:
                raise PersonalInsightStateError("Grant unavailable")
            if grant["expires_at"] <= now:
                raise PersonalInsightStateError("Grant expired")
            if grant["job_id_sha256"] != job_hash:
                raise PersonalInsightStateError("Grant job mismatch")
            if grant["state"] != "claimed":
                raise PersonalInsightStateError("Dataset already requested")
            grant["state"] = "fetching"
            grant["fetch_started_at"] = now
            return deepcopy(grant)

    def complete_fetch(
        self, grant_id, job_hash, checksum, byte_count, source_records, now
    ):
        with self.lock:
            grant = self.grants[grant_id]
            if grant["state"] != "fetching" or grant["job_id_sha256"] != job_hash:
                raise PersonalInsightStateError("Dataset fetch unavailable")
            grant["state"] = "fetched"
            grant["dataset_sha256"] = checksum
            grant["dataset_byte_count"] = byte_count
            grant["source_records"] = deepcopy(source_records)
            grant["fetched_at"] = now
            return deepcopy(grant)

    def fail_fetch(self, grant_id, job_hash, reason, now):
        with self.lock:
            grant = self.grants[grant_id]
            if grant["state"] == "fetching" and grant["job_id_sha256"] == job_hash:
                grant["state"] = "failed"
                grant["failure_reason"] = reason
                grant["failed_at"] = now
            return deepcopy(grant)

    def complete_run(
        self,
        grant_id,
        token_hash,
        job_hash,
        run_hash,
        result_hash,
        result_expires_at,
        now,
    ):
        with self.lock:
            grant = self.grants[grant_id]
            if (
                grant["token_sha256"] != token_hash
                or grant["job_id_sha256"] != job_hash
                or grant["run_id_sha256"] != run_hash
            ):
                raise PersonalInsightStateError("Run unavailable")
            if grant["state"] == "complete":
                if grant["result_sha256"] == result_hash:
                    return deepcopy(grant)
                raise PersonalInsightStateError("Run already completed")
            if grant["state"] != "fetched":
                raise PersonalInsightStateError("Run unavailable")
            grant["state"] = "complete"
            grant["result_sha256"] = result_hash
            grant["result_expires_at"] = result_expires_at
            grant["completed_at"] = now
            return deepcopy(grant)

    def save_capability(self, capability_id, data):
        with self.lock:
            key = "capability:" + capability_id
            if key in self.grants:
                raise RuntimeError("conflict")
            self.grants[key] = deepcopy(data)

    def consume_capability(
        self, capability_id, token_hash, run_hash, action, now
    ):
        with self.lock:
            capability = self.grants["capability:" + capability_id]
            if (
                capability["token_sha256"] != token_hash
                or capability["run_id_sha256"] != run_hash
                or capability["action"] != action
            ):
                raise PersonalInsightStateError("Capability unavailable")
            if capability["expires_at"] <= now:
                raise PersonalInsightStateError("Capability expired")
            if capability["consumed_at"] is not None:
                raise PersonalInsightStateError("Capability already used")
            capability["consumed_at"] = now
            return deepcopy(capability)

    def consume_history_capability(
        self, capability_id, token_hash, history_id, action, now
    ):
        with self.lock:
            capability = self.grants["capability:" + capability_id]
            if (
                capability["token_sha256"] != token_hash
                or capability["history_id"] != history_id
                or capability["action"] != action
            ):
                raise PersonalInsightStateError("Capability unavailable")
            if capability["expires_at"] <= now:
                raise PersonalInsightStateError("Capability expired")
            if capability["consumed_at"] is not None:
                raise PersonalInsightStateError("Capability already used")
            capability["consumed_at"] = now
            return deepcopy(capability)


def write_document(
    upload_root,
    owner,
    index,
    timestamp=None,
    valid=True,
    interval_base=700,
    record_type="rest",
):
    timestamp = timestamp or "2026-07-{:02d}_120000".format(index + 1)
    record = (
        generated_sleep_record(
            timestamp, interval_base + index, "device-{}".format(index)
        )
        if record_type == "sleep"
        else generated_record(
            timestamp, interval_base + index, valid, "device-{}".format(index)
        )
    )
    path = upload_root / owner / "private-file-{}.json".format(index)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record), encoding="utf-8")
    canonical = json.dumps(record, sort_keys=True, separators=(",", ":")).encode()
    return {
        "_id": "private-record-{}".format(index),
        "created_by": owner,
        "file_path": str(path),
        "content_hash": hashlib.sha256(canonical).hexdigest(),
        "record_contract_version": "brainstem-record-v1",
        "record_type": record_type,
        "recognized_payloads": ["hbr_rr"],
    }


def build_setup(
    tmp_path,
    policy=personal_insight.LEGACY_POLICY,
    interval_base=700,
    record_type="rest",
    document_count=20,
):
    now = [1_800_000_000]
    ids = iter("{:032x}".format(index) for index in range(1, 100))
    user = {
        "_id": "private-user",
        "public_address": ACCOUNT.address,
        "is_access_blocked": False,
        "usage_flag": "ACCEPTED",
        "guidelines_acceptance_flag": "ACCEPTED",
    }
    other = {
        "_id": "other-user",
        "public_address": OTHER_ACCOUNT.address,
        "is_access_blocked": False,
        "usage_flag": "ACCEPTED",
        "guidelines_acceptance_flag": "ACCEPTED",
    }
    documents = [
        write_document(
            tmp_path / "data",
            ACCOUNT.address,
            index,
            interval_base=interval_base,
            record_type=record_type,
        )
        for index in range(document_count)
    ]
    if record_type == "rest":
        documents.append(
            write_document(
                tmp_path / "data",
                ACCOUNT.address,
                20,
                timestamp="2026-07-31_120000",
                valid=False,
                interval_base=interval_base,
            )
        )
    other_document = write_document(
        tmp_path / "data",
        OTHER_ACCOUNT.address,
        99,
        "2026-07-30_120000",
        interval_base=interval_base,
        record_type=record_type,
    )
    documents.append(other_document)
    dao = MemoryPersonalDao()
    users = MemoryUsers({user["_id"]: user, other["_id"]: other})
    metadata = MemoryMetadata(documents)
    auth = MemoryAuth(user)
    service = BrainstemPersonalInsightService(
        auth_service=auth,
        personal_dao=dao,
        metadata_dao=metadata,
        users_dao=users,
        upload_root=tmp_path / "data",
        algorithm_image_digest=DIGEST,
        policy=policy,
        reference_state=(
            (lambda *_args, **_kwargs: "current")
            if policy.reference_sha256 is not None
            else None
        ),
        clock=lambda: now[0],
        nonce_factory=lambda: "n" * 43,
        id_factory=lambda: next(ids),
        secret_factory=lambda: "s" * 43,
    )
    return service, now, dao, users, metadata, auth, other_document


@pytest.fixture
def setup(tmp_path):
    return build_setup(tmp_path)


def approve(service):
    challenge = service.create_challenge("participant-session", ORIGIN)
    signature = Account.sign_message(
        encode_defunct(text=challenge["message"]), private_key=PRIVATE_KEY
    ).signature.hex()
    grant = service.exchange(
        "participant-session",
        ORIGIN,
        challenge["challengeId"],
        signature,
    )
    return challenge, signature, grant


def test_one_approval_exports_only_latest_sixteen_eligible_records(setup):
    service, _now, dao, _users, _metadata, _auth, other_document = setup
    challenge, signature, grant = approve(service)
    token = grant["grant"]
    assert service.claim(token, JOB_A, RUN_A)["status"] == "claimed"
    assert service.claim(token, JOB_A, RUN_A)["status"] == "claimed"
    with pytest.raises(PersonalInsightError):
        service.claim(token, JOB_B, RUN_A)
    with pytest.raises(PersonalInsightError):
        service.claim(token, JOB_A, RUN_B)

    artifact = service.fetch(token, JOB_A)
    assert artifact.dataset["schema"] == "brainstem.personal-resting-rr/v1"
    assert artifact.dataset["policy"] == "brainstem.personal-resting-rr/latest-16/v1"
    assert [
        recording["rrIntervalsMs"][0]
        for recording in artifact.dataset["recordings"]
    ] == list(range(704, 720))
    assert len(artifact.body) < 1024 * 1024
    assert hashlib.sha256(artifact.body).hexdigest() == artifact.checksum
    with pytest.raises(PersonalInsightError):
        service.fetch(token, JOB_A)

    text = artifact.body.decode()
    for canary in (
        ACCOUNT.address,
        OTHER_ACCOUNT.address,
        "private-user",
        "other-user",
        "private-record",
        "private-file",
        "device-",
        "2026-07",
        other_document["_id"],
        JOB_A,
        token,
    ):
        assert canary not in text
    stored_challenge = next(iter(dao.challenges.values()))
    stored_grant = next(iter(dao.grants.values()))
    assert "message" not in stored_challenge
    assert "address" not in stored_challenge
    assert token not in json.dumps(stored_grant)
    assert signature not in json.dumps(stored_grant)
    assert stored_grant["state"] == "fetched"
    assert len(stored_grant["source_records"]) == 16


def test_methods_policy_binds_evidence_and_exports_only_its_exact_shape(tmp_path):
    policy = personal_insight.personal_insight_policy(
        "resting-hrv-methods",
        approved_manifest_sha256="3" * 64,
        reference_sha256="4" * 64,
    )
    service, _now, _dao, _users, _metadata, _auth, _other = build_setup(
        tmp_path, policy, interval_base=1000
    )
    challenge, _signature, grant = approve(service)
    assert "Insight: brainstem.resting-hrv-methods/v1" in challenge["message"]
    assert "Approved Manifest SHA256: {}".format("3" * 64) in challenge["message"]
    assert "Cohort Reference SHA256: {}".format("4" * 64) in challenge["message"]

    claimed = service.claim(grant["grant"], JOB_A, RUN_A)
    assert claimed == {
        "status": "claimed",
        "historyId": claimed["historyId"],
        "expiresAt": "2027-01-15T08:05:00Z",
        "analysisId": "brainstem.resting-hrv-methods/v1",
        "algorithmVersion": "0.1.0",
        "algorithmImageDigest": DIGEST,
        "inputSchema": "brainstem.personal-resting-hrv-methods/v1",
        "inputPolicy": "brainstem.personal-resting-hrv-methods/latest-16/v1",
        "resultSchema": "brainstem.insight-result/v1",
        "resultProfile": "brainstem.resting-hrv-methods-personal/v1",
        "candidateManifestSha256": personal_insight.METHODS_CANDIDATE_SHA256,
        "approvedManifestSha256": "3" * 64,
        "referenceSha256": "4" * 64,
        "evidenceTier": "E2_brainstem_compatible_exploratory",
        "useClass": "methods_only",
        "clinicalUse": "prohibited",
        "maximumRecordings": 16,
        "audience": "brainstem-ocean-node",
    }
    artifact = service.fetch(grant["grant"], JOB_A)
    assert set(artifact.dataset) == {"schema", "recordings"}
    assert artifact.dataset["schema"] == (
        "brainstem.personal-resting-hrv-methods/v1"
    )
    assert len(artifact.dataset["recordings"]) == 16
    assert personal_insight._slot(
        ORIGIN, "private-user", policy.analysis_id
    ) != personal_insight._slot(
        ORIGIN, "private-user", personal_insight.LEGACY_POLICY.analysis_id
    )


def test_methods_policy_is_disabled_without_release_and_reference_digests():
    with pytest.raises(PersonalInsightError, match="personal_insight_disabled"):
        personal_insight.personal_insight_policy("resting-hrv-methods")


def test_sample_entropy_policy_binds_evidence_and_exports_latest_four(tmp_path):
    policy = personal_insight.personal_insight_policy(
        "resting-rr-sample-entropy",
        approved_manifest_sha256="5" * 64,
        reference_sha256="6" * 64,
    )
    service, _now, _dao, _users, _metadata, _auth, _other = build_setup(
        tmp_path, policy, interval_base=1000
    )
    challenge, _signature, grant = approve(service)

    assert "Insight: brainstem.resting-rr-sample-entropy/v1" in challenge["message"]
    assert "Maximum Recordings: 4" in challenge["message"]
    service.claim(grant["grant"], JOB_A, RUN_A)
    artifact = service.fetch(grant["grant"], JOB_A)
    assert set(artifact.dataset) == {"schema", "recordings"}
    assert artifact.dataset["schema"] == (
        "brainstem.personal-resting-sample-entropy/v1"
    )
    assert len(artifact.dataset["recordings"]) == 4
    assert policy.candidate_manifest_sha256 == (
        personal_insight.SAMPLE_ENTROPY_CANDIDATE_SHA256
    )


def test_withdrawn_reference_blocks_new_run_and_historical_result_access(tmp_path):
    state = ["current"]
    policy = personal_insight.personal_insight_policy(
        "resting-hrv-methods",
        approved_manifest_sha256="3" * 64,
        reference_sha256="4" * 64,
    )
    service, _now, _dao, _users, _metadata, _auth, _other = build_setup(
        tmp_path, policy, interval_base=1000
    )
    service.reference_state = lambda *_args, **_kwargs: state[0]
    _challenge, _signature, grant = approve(service)
    service.claim(grant["grant"], JOB_A, RUN_A)
    service.fetch(grant["grant"], JOB_A)
    service.complete(grant["grant"], JOB_A, RUN_A, RESULT_SHA256)

    state[0] = "unavailable"
    with pytest.raises(PersonalInsightError, match="reference_unavailable"):
        service.create_challenge("participant-session", ORIGIN)
    with pytest.raises(PersonalInsightError, match="run_revoked"):
        service.revalidate_history(
            next(iter(service.personal_dao.grants.values()))["history_id"]
        )
    historical = service.history("participant-session", ORIGIN)[0]
    assert historical["status"] == "revoked"
    assert historical["correctionState"] == "unavailable"


def test_history_uses_the_reference_bound_to_its_grant(tmp_path):
    first_reference = "4" * 64
    second_reference = "5" * 64
    first_policy = personal_insight.personal_insight_policy(
        "resting-hrv-methods",
        approved_manifest_sha256="3" * 64,
        reference_sha256=first_reference,
    )
    service, _now, _dao, _users, _metadata, _auth, _other = build_setup(
        tmp_path, first_policy, interval_base=1000
    )
    _challenge, _signature, grant = approve(service)
    history_id = service.claim(grant["grant"], JOB_A, RUN_A)["historyId"]
    service.fetch(grant["grant"], JOB_A)
    service.complete(grant["grant"], JOB_A, RUN_A, RESULT_SHA256)

    service.policy = personal_insight.personal_insight_policy(
        "resting-hrv-methods",
        approved_manifest_sha256="3" * 64,
        reference_sha256=second_reference,
    )
    service.reference_state = lambda _analysis, reference, **_pins: (
        "superseded" if reference == first_reference else "current"
    )

    assert service.revalidate_history(history_id)["status"] == "authorized"
    historical = service.history("participant-session", ORIGIN)[0]
    assert historical["status"] == "complete"
    assert historical["correctionState"] == "superseded"


def test_sleep_baseline_exports_latest_seven_qualified_nights(tmp_path):
    policy = personal_insight.personal_insight_policy(
        "sleep-baseline",
        approved_manifest_sha256="7" * 64,
        reference_sha256="8" * 64,
    )
    service, _now, _dao, _users, _metadata, _auth, _other = build_setup(
        tmp_path,
        policy,
        interval_base=900,
        record_type="sleep",
        document_count=9,
    )
    challenge, _signature, grant = approve(service)

    assert "Insight: brainstem.sleep-baseline/v1" in challenge["message"]
    assert "Maximum Recordings: 7" in challenge["message"]
    service.claim(grant["grant"], JOB_A, RUN_A)
    artifact = service.fetch(grant["grant"], JOB_A)
    assert set(artifact.dataset) == {"schema", "policy", "recordings"}
    assert artifact.dataset["schema"] == "brainstem.personal-sleep-baseline/v1"
    assert artifact.dataset["policy"] == (
        "brainstem.personal-sleep-baseline/latest-7/v1"
    )
    assert len(artifact.dataset["recordings"]) == 7
    assert all(
        item["allowedUse"] == "private_descriptive_self_only"
        and item["recordingType"] == "sleep"
        for item in artifact.dataset["recordings"]
    )
    text = artifact.body.decode()
    assert ACCOUNT.address not in text
    assert "device-" not in text
    assert "2026-07" not in text


def test_latest_selection_uses_content_hash_to_break_timestamp_ties(setup):
    service, _now, _dao, _users, metadata, _auth, _other = setup
    eligible = []
    for document in metadata.documents.values():
        if document["created_by"] != ACCOUNT.address:
            continue
        path = Path(document["file_path"])
        record = json.loads(path.read_text(encoding="utf-8"))
        payload = record["datasource"]["sensor"]["payloads"]["hbr_rr"]["data"]
        if "not-a-number" in payload:
            continue
        record["timestamp"] = "2026-07-27_120000"
        path.write_text(json.dumps(record), encoding="utf-8")
        canonical = json.dumps(
            record, sort_keys=True, separators=(",", ":")
        ).encode()
        document["content_hash"] = hashlib.sha256(canonical).hexdigest()
        eligible.append((document, int(payload.split(",", 2)[2].split(";", 1)[0])))

    expected = [
        interval
        for _document, interval in sorted(
            eligible, key=lambda value: value[0]["content_hash"]
        )[-16:]
    ]
    artifact = service._build("private-user")
    assert [
        recording["rrIntervalsMs"][0]
        for recording in artifact.dataset["recordings"]
    ] == expected


def test_shared_source_and_interval_limits_fail_closed(tmp_path, monkeypatch):
    owner = ACCOUNT.address
    document = write_document(tmp_path / "data", owner, 0)
    source = Path(document["file_path"])

    symlink = source.with_name("linked.json")
    symlink.symlink_to(source)
    document["file_path"] = str(symlink)
    with pytest.raises(record_export.RecordExportError, match="source_symlink_rejected"):
        record_export.resting_rr_record(tmp_path / "data", owner, document)

    document["file_path"] = str(source.with_name("missing.json"))
    with pytest.raises(record_export.RecordExportError, match="source_not_regular_file"):
        record_export.resting_rr_record(tmp_path / "data", owner, document)

    document["file_path"] = str(source)
    with monkeypatch.context() as scoped:
        scoped.setattr(record_export, "MAX_SOURCE_BYTES", 8)
        with pytest.raises(record_export.RecordExportError, match="source_too_large"):
            record_export.resting_rr_record(tmp_path / "data", owner, document)

    with monkeypatch.context() as scoped:
        scoped.setattr(record_export, "MAX_INTERVALS_PER_RECORDING", 3)
        with pytest.raises(record_export.RecordExportError) as error:
            record_export.resting_rr_record(tmp_path / "data", owner, document)
        assert error.value.code == "interval_limit_exceeded"
        assert error.value.status_code == 413


def test_personal_export_size_limit_fails_closed(setup, monkeypatch):
    service, _now, _dao, _users, _metadata, _auth, _other = setup
    monkeypatch.setattr(personal_insight, "MAX_EXPORT_BYTES", 1)
    with pytest.raises(PersonalInsightError) as error:
        service._build("private-user")
    assert error.value.code == "export_byte_limit_exceeded"
    assert error.value.status_code == 413


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("purpose", "other"),
        ("scope", "participant:all"),
        ("algorithm_image_digest", "sha256:" + "3" * 64),
        ("input_schema", "brainstem.private-rr-cohort/v1"),
        ("maximum_recordings", 17),
        ("result_audience", "public"),
        ("payment", "required"),
        ("node_audience", "other-node"),
        ("message", "changed"),
    ],
)
def test_any_challenge_contract_change_fails_before_grant(setup, field, value):
    service, _now, dao, _users, _metadata, _auth, _other = setup
    challenge = service.create_challenge("participant-session", ORIGIN)
    next(iter(dao.challenges.values()))[field] = value
    signature = Account.sign_message(
        encode_defunct(text=challenge["message"]), private_key=PRIVATE_KEY
    ).signature.hex()
    with pytest.raises(PersonalInsightError):
        service.exchange(
            "participant-session", ORIGIN, challenge["challengeId"], signature
        )
    assert dao.grants == {}


def test_wrong_session_origin_signature_expiry_and_replay_fail(setup):
    service, now, dao, _users, _metadata, auth, _other = setup
    with pytest.raises(PersonalInsightError):
        service.create_challenge("wrong-session", ORIGIN)
    challenge = service.create_challenge("participant-session", ORIGIN)
    wrong_signature = Account.sign_message(
        encode_defunct(text=challenge["message"]), private_key=OTHER_ACCOUNT.key
    ).signature.hex()
    with pytest.raises(PersonalInsightError):
        service.exchange(
            "participant-session", ORIGIN, challenge["challengeId"], wrong_signature
        )
    now[0] += 301
    with pytest.raises(PersonalInsightError, match="challenge_expired"):
        service.exchange(
            "participant-session", ORIGIN, challenge["challengeId"], wrong_signature
        )
    now[0] -= 301
    _, _signature, grant = approve(service)
    with pytest.raises(PersonalInsightError):
        service.exchange(
            "participant-session",
            ORIGIN,
            next(iter(dao.challenges.values()))["challenge_id"],
            "0x" + "00" * 65,
        )
    auth.valid = False
    with pytest.raises(PersonalInsightError):
        service.create_challenge("participant-session", ORIGIN)
    assert grant["grant"]


def test_concurrent_exchange_creates_at_most_one_grant(setup):
    service, _now, dao, _users, _metadata, _auth, _other = setup
    challenge = service.create_challenge("participant-session", ORIGIN)
    signature = Account.sign_message(
        encode_defunct(text=challenge["message"]), private_key=PRIVATE_KEY
    ).signature.hex()
    barrier = threading.Barrier(2)

    def exchange():
        barrier.wait()
        try:
            return service.exchange(
                "participant-session",
                ORIGIN,
                challenge["challengeId"],
                signature,
            )
        except PersonalInsightError:
            return None

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _index: exchange(), range(2)))
    assert len([result for result in results if result]) == 1
    assert len(dao.grants) == 1


def test_consent_deletion_and_source_drift_are_rechecked(setup, tmp_path):
    service, _now, dao, users, metadata, _auth, _other = setup
    challenge, _signature, grant = approve(service)
    users.users["private-user"]["usage_flag"] = "REJECTED"
    with pytest.raises(PersonalInsightError):
        service.claim(grant["grant"], JOB_A, RUN_A)

    users.users["private-user"]["usage_flag"] = "ACCEPTED"
    service.claim(grant["grant"], JOB_A, RUN_A)
    users.users["private-user"]["guidelines_acceptance_flag"] = "REJECTED"
    with pytest.raises(PersonalInsightError):
        service.fetch(grant["grant"], JOB_A)
    assert next(iter(dao.grants.values()))["state"] == "failed"

    users.users["private-user"]["guidelines_acceptance_flag"] = "ACCEPTED"
    fresh_service, _fresh_now, _fresh_dao, _fresh_users, _fresh_metadata, _fresh_auth, _fresh_other = build_setup(
        tmp_path / "fresh"
    )
    fresh_challenge = fresh_service.create_challenge("participant-session", ORIGIN)
    assert fresh_challenge["challengeId"]
    fresh_metadata = fresh_service.metadata_dao
    fresh_metadata.documents = {
        key: value
        for key, value in fresh_metadata.documents.items()
        if value["created_by"] != ACCOUNT.address
    }
    signature = Account.sign_message(
        encode_defunct(text=fresh_challenge["message"]), private_key=PRIVATE_KEY
    ).signature.hex()
    fresh_grant = fresh_service.exchange(
        "participant-session",
        ORIGIN,
        fresh_challenge["challengeId"],
        signature,
    )
    with pytest.raises(PersonalInsightError, match="no_eligible_records"):
        fresh_service.claim(fresh_grant["grant"], JOB_A, RUN_A)

    assert challenge["challengeId"]
    first = next(
        document
        for document in metadata.documents.values()
        if document["created_by"] == ACCOUNT.address
    )
    Path(first["file_path"]).write_text("{}", encoding="utf-8")
    with pytest.raises(PersonalInsightError):
        service._build("private-user")


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("purpose", "other"),
        ("algorithm_image_digest", "sha256:" + "3" * 64),
        ("input_policy", "latest"),
        ("result_profile", "other"),
        ("candidate_manifest_sha256", "f" * 64),
        ("approved_manifest_sha256", "f" * 64),
        ("reference_sha256", "f" * 64),
        ("evidence_tier", "E3_brainstem_validated_research"),
        ("use_class", "protocol_bound_research"),
        ("clinical_use", "allowed"),
        ("maximum_recordings", 100),
        ("node_audience", "public"),
    ],
)
def test_changed_grant_contract_cannot_be_claimed(setup, field, value):
    service, _now, dao, _users, _metadata, _auth, _other = setup
    _challenge, _signature, grant = approve(service)
    next(iter(dao.grants.values()))[field] = value
    with pytest.raises(PersonalInsightError):
        service.claim(grant["grant"], JOB_A, RUN_A)


def test_grant_expiry_and_token_or_job_mismatch_fail(setup):
    service, now, _dao, _users, _metadata, _auth, _other = setup
    _challenge, _signature, grant = approve(service)
    with pytest.raises(PersonalInsightError):
        service.claim(grant["grant"][:-1] + "x", JOB_A, RUN_A)
    now[0] += 301
    with pytest.raises(PersonalInsightError):
        service.claim(grant["grant"], JOB_A, RUN_A)
    with pytest.raises(PersonalInsightError):
        service.claim(grant["grant"], "not-a-job", RUN_A)


def test_completion_and_access_capabilities_are_one_use_and_self_only(setup):
    service, now, _dao, users, metadata, auth, _other = setup
    _challenge, _signature, grant = approve(service)
    token = grant["grant"]
    service.claim(token, JOB_A, RUN_A)
    service.fetch(token, JOB_A)
    newer = write_document(
        service.upload_root, ACCOUNT.address, 21, "2026-08-01_120000"
    )
    metadata.documents[newer["_id"]] = newer
    completed = service.complete(
        token, JOB_A, RUN_A, RESULT_SHA256
    )
    assert completed["status"] == "complete"
    assert service.complete(token, JOB_A, RUN_A, RESULT_SHA256) == completed

    access = service.issue_access(
        "participant-session", ORIGIN, token, RUN_A, "result"
    )
    authorized = service.consume_access(
        access["capability"], RUN_A, "result"
    )
    assert authorized == {
        "status": "authorized",
        "action": "result",
        "runId": RUN_A,
        "resultSha256": RESULT_SHA256,
    }
    with pytest.raises(PersonalInsightError):
        service.consume_access(access["capability"], RUN_A, "result")
    with pytest.raises(PersonalInsightError):
        service.issue_access(
            "participant-session", ORIGIN, token, RUN_B, "result"
        )
    auth.user = users.users["other-user"]
    with pytest.raises(PersonalInsightError):
        service.issue_access(
            "participant-session", ORIGIN, token, RUN_A, "result"
        )
    auth.user = users.users["private-user"]

    status_access = service.issue_access(
        "participant-session", ORIGIN, token, RUN_A, "status"
    )
    users.users["private-user"]["usage_flag"] = "REJECTED"
    with pytest.raises(PersonalInsightError):
        service.consume_access(status_access["capability"], RUN_A, "status")
    users.users["private-user"]["usage_flag"] = "ACCEPTED"
    now[0] += 14 * 24 * 60 * 60 + 1
    with pytest.raises(PersonalInsightError):
        service.issue_access(
            "participant-session", ORIGIN, token, RUN_A, "result"
        )


def test_history_is_owner_bound_bounded_and_uses_one_use_capabilities(setup):
    service, _now, dao, users, metadata, auth, _other = setup
    _challenge, _signature, grant = approve(service)
    token = grant["grant"]
    claimed = service.claim(token, JOB_A, RUN_A)
    history_id = claimed["historyId"]
    assert len(history_id) == 64
    assert service.history("participant-session", ORIGIN) == [
        {
            "historyId": history_id,
            "analysisId": "brainstem.personal-resting-heart-overview/v1",
            "algorithmVersion": "1.0.0",
            "algorithmImageDigest": DIGEST,
            "status": "pending",
            "createdAt": "2027-01-15T00:00:00Z",
            "completedAt": None,
            "expiresAt": None,
            "correctionState": "current",
            "updateAvailable": False,
        }
    ]

    service.fetch(token, JOB_A)
    service.complete(token, JOB_A, RUN_A, RESULT_SHA256)
    entry = service.history("participant-session", ORIGIN)[0]
    assert entry["status"] == "complete"
    assert entry["expiresAt"] is not None
    assert entry["updateAvailable"] is False
    new_document = write_document(
        service.upload_root,
        ACCOUNT.address,
        21,
        timestamp="2026-08-01_120000",
    )
    metadata.documents[new_document["_id"]] = new_document
    assert service.history("participant-session", ORIGIN)[0][
        "updateAvailable"
    ] is True
    serialized = json.dumps(entry)
    for private in (
        token,
        JOB_A,
        RUN_A,
        ACCOUNT.address,
        "private-user",
        "private-record",
        RESULT_SHA256,
    ):
        assert private not in serialized

    access = service.issue_history_access(
        "participant-session", ORIGIN, history_id, "result"
    )
    assert set(access) == {
        "capability",
        "action",
        "historyId",
        "expiresAt",
    }
    assert service.consume_history_access(
        access["capability"], history_id, "result"
    ) == {
        "status": "authorized",
        "action": "result",
        "historyId": history_id,
        "resultSha256": RESULT_SHA256,
    }
    with pytest.raises(PersonalInsightError):
        service.consume_history_access(
            access["capability"], history_id, "result"
        )

    auth.user = users.users["other-user"]
    with pytest.raises(PersonalInsightError) as wrong_owner:
        service.issue_history_access(
            "participant-session", ORIGIN, history_id, "result"
        )
    assert wrong_owner.value.status_code == 404
    auth.user = users.users["private-user"]

    selected_id = next(iter(dao.grants.values()))["source_records"][0]["id"]
    del metadata.documents[selected_id]
    revoked = service.history("participant-session", ORIGIN)[0]
    assert revoked["status"] == "revoked"
    assert revoked["updateAvailable"] is False
    assert revoked["correctionState"] == "revoked"
    with pytest.raises(PersonalInsightError):
        service.issue_history_access(
            "participant-session", ORIGIN, history_id, "result"
        )

    with pytest.raises(PersonalInsightError):
        service.history("participant-session", ORIGIN, limit=0)


def test_existing_completed_run_without_history_remains_readable(setup):
    service, _now, dao, _users, _metadata, _auth, _other = setup
    _challenge, _signature, grant = approve(service)
    token = grant["grant"]
    grant_id = token.split(".", 1)[0]
    service.claim(token, JOB_A, RUN_A)
    service.fetch(token, JOB_A)
    service.complete(token, JOB_A, RUN_A, RESULT_SHA256)
    del dao.grants[grant_id]["history_id"]

    access = service.issue_access(
        "participant-session", ORIGIN, token, RUN_A, "result"
    )
    assert service.consume_access(
        access["capability"], RUN_A, "result"
    )["resultSha256"] == RESULT_SHA256


def test_node_revalidation_authorizes_only_a_current_completed_run(setup):
    service, _now, _dao, users, _metadata, _auth, _other = setup
    _challenge, _signature, grant = approve(service)
    token = grant["grant"]
    service.claim(token, JOB_A, RUN_A)
    service.fetch(token, JOB_A)
    service.complete(token, JOB_A, RUN_A, RESULT_SHA256)

    assert service.revalidate(token, JOB_A, RUN_A) == {
        "status": "authorized",
        "jobId": JOB_A,
        "runId": RUN_A,
    }
    with pytest.raises(PersonalInsightError) as wrong:
        service.revalidate(token[:-1] + "x", JOB_A, RUN_A)
    assert wrong.value.status_code == 401

    users.users["private-user"]["usage_flag"] = "REJECTED"
    with pytest.raises(PersonalInsightError) as revoked:
        service.revalidate(token, JOB_A, RUN_A)
    assert revoked.value.status_code == 410


def test_node_revalidation_marks_selected_source_deletion_terminal(setup):
    service, _now, dao, _users, metadata, _auth, _other = setup
    _challenge, _signature, grant = approve(service)
    token = grant["grant"]
    service.claim(token, JOB_A, RUN_A)
    service.fetch(token, JOB_A)
    service.complete(token, JOB_A, RUN_A, RESULT_SHA256)
    selected_id = next(iter(dao.grants.values()))["source_records"][0]["id"]
    del metadata.documents[selected_id]

    with pytest.raises(PersonalInsightError) as deleted:
        service.revalidate(token, JOB_A, RUN_A)
    assert deleted.value.status_code == 410


def test_history_revalidation_tracks_consent_deletion_and_expiry(setup):
    service, now, dao, users, metadata, _auth, _other = setup
    _challenge, _signature, grant = approve(service)
    token = grant["grant"]
    history_id = service.claim(token, JOB_A, RUN_A)["historyId"]
    service.fetch(token, JOB_A)
    service.complete(token, JOB_A, RUN_A, RESULT_SHA256)

    assert service.revalidate_history(history_id) == {
        "status": "authorized",
        "historyId": history_id,
    }

    users.users["private-user"]["usage_flag"] = "REJECTED"
    with pytest.raises(PersonalInsightError) as revoked:
        service.revalidate_history(history_id)
    assert revoked.value.status_code == 410

    users.users["private-user"]["usage_flag"] = "ACCEPTED"
    selected_id = next(iter(dao.grants.values()))["source_records"][0]["id"]
    selected_document = metadata.documents.pop(selected_id)
    with pytest.raises(PersonalInsightError) as deleted:
        service.revalidate_history(history_id)
    assert deleted.value.status_code == 410

    metadata.documents[selected_id] = selected_document
    now[0] += 14 * 24 * 60 * 60 + 1
    with pytest.raises(PersonalInsightError) as expired:
        service.revalidate_history(history_id)
    assert expired.value.status_code == 410
