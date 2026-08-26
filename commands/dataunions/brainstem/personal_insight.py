from dataclasses import dataclass
import hashlib
import hmac
import re
import secrets
import time
import uuid
from pathlib import Path
from typing import Any, Dict, Iterable, Tuple
from urllib.parse import urlparse

from commands.dataunions.brainstem.consent import has_brainstem_data_consent
from commands.dataunions.brainstem.record_contract import CONTRACT_VERSION
from commands.dataunions.brainstem.record_export import (
    RecordExportError,
    RestingRRRecord,
    canonical_json,
    full_night_rr_record,
    resting_rr_record,
)
from commands.users.participant_auth import (
    IDENTIFIER,
    SESSION_SECRET,
    ParticipantAuthError,
    checksum_address,
    rfc3339,
    verify_wallet_signature,
)
from dao.personal_insight_dao import PersonalInsightStateError


SCOPE = "participant:self:insight:run-once"
RESOURCE = "urn:brainstem:scope:participant:self:insight:run-once"
AUDIENCE = "brainstem-ocean-node"
MAX_RECORDINGS = 16
MAX_EXPORT_BYTES = 8 * 1024 * 1024
MAX_INSPECTED_RECORDS = 20_000
JOB_ID_PATTERN = re.compile(r"^[0-9a-f]{64}$")
RUN_ID_PATTERN = re.compile(r"^[0-9a-f]{32}$")
HISTORY_ID_PATTERN = re.compile(r"^[0-9a-f]{64}$")
DIGEST_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
ACCESS_ACTIONS = {"status", "result"}
MAX_HISTORY_ENTRIES = 50
MAX_HISTORY_SCAN = 1000
LEGACY_STATEMENT = (
    "Run one private resting-heart overview using only eligible resting R-R "
    "intervals and recording durations. Identity, device details, and dates "
    "are excluded. Only you can access the result. This is not a transaction, "
    "payment, study enrollment, diagnosis, medical advice, future "
    "authorization, or data change."
)
METHODS_STATEMENT = (
    "Run one private resting-heart variability analysis using only eligible "
    "resting R-R intervals. Your result is compared with a frozen reviewed "
    "group reference; no other participant's records are included. Identity, "
    "device details, and dates are excluded. This is not a transaction, "
    "payment, diagnosis, medical advice, future authorization, or data change."
)
SAMPLE_ENTROPY_STATEMENT = (
    "Run one private resting-rhythm complexity analysis using only up to four "
    "eligible resting R-R recordings. Your result is compared with a frozen "
    "reviewed group reference; no other participant's records are included. "
    "Identity, device details, and dates are excluded. This is not a "
    "transaction, payment, diagnosis, medical advice, future authorization, "
    "or data change."
)
SLEEP_BASELINE_STATEMENT = (
    "Run one private sleep recording baseline using only up to seven "
    "qualifying full-night R-R recordings. Your result is compared with a "
    "frozen reviewed group reference; no other participant's records are "
    "included. Identity, device details, and dates are excluded. This is "
    "not a transaction, payment, sleep-stage or apnea analysis, diagnosis, "
    "medical advice, future authorization, or data change."
)


@dataclass(frozen=True)
class PersonalInsightPolicy:
    slug: str
    analysis_id: str
    algorithm_version: str
    purpose: str
    input_schema: str
    input_policy: str
    result_schema: str
    result_profile: str
    statement: str
    exporter: str
    candidate_manifest_sha256: str | None
    approved_manifest_sha256: str | None
    reference_sha256: str | None
    evidence_tier: str
    use_class: str
    clinical_use: str = "prohibited"
    maximum_recordings: int = MAX_RECORDINGS


LEGACY_POLICY = PersonalInsightPolicy(
    slug="resting-heart-overview",
    analysis_id="brainstem.personal-resting-heart-overview/v1",
    algorithm_version="1.0.0",
    purpose="brainstem.personal-insight.resting-heart-overview/v1",
    input_schema="brainstem.personal-resting-rr/v1",
    input_policy="brainstem.personal-resting-rr/latest-16/v1",
    result_schema="brainstem.c2d-result/v1",
    result_profile="brainstem.personal-resting-heart-overview/v1",
    statement=LEGACY_STATEMENT,
    exporter="resting_rr_latest_16",
    candidate_manifest_sha256=None,
    approved_manifest_sha256=None,
    reference_sha256=None,
    evidence_tier="E2_brainstem_compatible_exploratory",
    use_class="methods_only",
)

METHODS_CANDIDATE_SHA256 = (
    "15dbf8544c87d81c06f5e512b00e9fe39dd6431dd1a4079a97da68a3f92721c1"
)
SAMPLE_ENTROPY_CANDIDATE_SHA256 = (
    "65002ab13f02f812c611085c0295b81dc90ec7ffacc79f9ff4927e81e9070bdd"
)
SLEEP_BASELINE_CANDIDATE_SHA256 = (
    "4c24414518539dd6ff2c1a166e6d588f01e3a3fa9572111fb15b6729c7c7300e"
)


def personal_insight_policy(
    value,
    *,
    approved_manifest_sha256=None,
    reference_sha256=None,
):
    if value in {LEGACY_POLICY.slug, LEGACY_POLICY.analysis_id}:
        return LEGACY_POLICY
    methods = value in {
        "resting-hrv-methods", "brainstem.resting-hrv-methods/v1"
    }
    sample_entropy = value in {
        "resting-rr-sample-entropy",
        "brainstem.resting-rr-sample-entropy/v1",
    }
    sleep_baseline = value in {
        "sleep-baseline",
        "brainstem.sleep-baseline/v1",
    }
    if not methods and not sample_entropy and not sleep_baseline:
        raise PersonalInsightError("personal_insight_not_found", 404)
    if (
        not isinstance(approved_manifest_sha256, str)
        or not SHA256_PATTERN.fullmatch(approved_manifest_sha256)
        or not isinstance(reference_sha256, str)
        or not SHA256_PATTERN.fullmatch(reference_sha256)
    ):
        raise PersonalInsightError("personal_insight_disabled", 503)
    if methods:
        slug = "resting-hrv-methods"
        analysis_id = "brainstem.resting-hrv-methods/v1"
        purpose = "brainstem.personal-insight.resting-hrv-methods/v1"
        input_schema = "brainstem.personal-resting-hrv-methods/v1"
        input_policy = "brainstem.personal-resting-hrv-methods/latest-16/v1"
        result_profile = "brainstem.resting-hrv-methods-personal/v1"
        statement = METHODS_STATEMENT
        exporter = "resting_hrv_methods_latest_16"
        candidate = METHODS_CANDIDATE_SHA256
        maximum_recordings = MAX_RECORDINGS
    elif sample_entropy:
        slug = "resting-rr-sample-entropy"
        analysis_id = "brainstem.resting-rr-sample-entropy/v1"
        purpose = "brainstem.personal-insight.resting-rr-sample-entropy/v1"
        input_schema = "brainstem.personal-resting-sample-entropy/v1"
        input_policy = "brainstem.personal-resting-sample-entropy/latest-4/v1"
        result_profile = "brainstem.resting-sample-entropy-personal/v1"
        statement = SAMPLE_ENTROPY_STATEMENT
        exporter = "resting_sample_entropy_latest_4"
        candidate = SAMPLE_ENTROPY_CANDIDATE_SHA256
        maximum_recordings = 4
    else:
        slug = "sleep-baseline"
        analysis_id = "brainstem.sleep-baseline/v1"
        purpose = "brainstem.personal-insight.sleep-baseline/v1"
        input_schema = "brainstem.personal-sleep-baseline/v1"
        input_policy = "brainstem.personal-sleep-baseline/latest-7/v1"
        result_profile = "brainstem.sleep-baseline-personal/v1"
        statement = SLEEP_BASELINE_STATEMENT
        exporter = "sleep_baseline_latest_7"
        candidate = SLEEP_BASELINE_CANDIDATE_SHA256
        maximum_recordings = 7
    return PersonalInsightPolicy(
        slug=slug,
        analysis_id=analysis_id,
        algorithm_version="0.1.0",
        purpose=purpose,
        input_schema=input_schema,
        input_policy=input_policy,
        result_schema="brainstem.insight-result/v1",
        result_profile=result_profile,
        statement=statement,
        exporter=exporter,
        candidate_manifest_sha256=candidate,
        approved_manifest_sha256=approved_manifest_sha256,
        reference_sha256=reference_sha256,
        evidence_tier="E2_brainstem_compatible_exploratory",
        use_class="methods_only",
        maximum_recordings=maximum_recordings,
    )


# Backwards-compatible names for existing tests and the named legacy policy.
INSIGHT_ID = LEGACY_POLICY.analysis_id
ALGORITHM_VERSION = LEGACY_POLICY.algorithm_version
PURPOSE = LEGACY_POLICY.purpose
INPUT_SCHEMA = LEGACY_POLICY.input_schema
INPUT_POLICY = LEGACY_POLICY.input_policy
RESULT_SCHEMA = LEGACY_POLICY.result_schema
RESULT_PROFILE = LEGACY_POLICY.result_profile
STATEMENT = LEGACY_POLICY.statement


class PersonalInsightError(RuntimeError):
    def __init__(self, code, status_code=400):
        super().__init__(code)
        self.code = code
        self.status_code = status_code


@dataclass(frozen=True)
class PersonalInsightArtifact:
    body: bytes
    checksum: str
    dataset: Dict[str, Any]
    private_sources: Tuple[Dict[str, str], ...]


def _sha256(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _matches(value, expected):
    return isinstance(value, str) and hmac.compare_digest(value, expected)


def _slot(origin, user_id, analysis_id=INSIGHT_ID):
    return _sha256(
        "personal-insight\0{}\0{}\0{}".format(origin, user_id, analysis_id)
    )[:32]


def _message(
    policy,
    origin,
    address,
    chain_id,
    nonce,
    challenge_id,
    issued_at,
    expires_at,
    algorithm_image_digest,
):
    return "\n".join(
        [
            "{} requests one Brainstem Insight with your Ethereum account:".format(
                urlparse(origin).netloc
            ),
            address,
            "",
            policy.statement,
            "",
            "URI: {}/participant/insights/{}".format(origin, policy.slug),
            "Version: 1",
            "Chain ID: {}".format(chain_id),
            "Nonce: {}".format(nonce),
            "Issued At: {}".format(rfc3339(issued_at)),
            "Expiration Time: {}".format(rfc3339(expires_at)),
            "Request ID: {}".format(challenge_id),
            "Purpose: {}".format(policy.purpose),
            "Scope: {}".format(SCOPE),
            "Insight: {}".format(policy.analysis_id),
            "Algorithm Image Digest: {}".format(algorithm_image_digest),
            "Input Schema: {}".format(policy.input_schema),
            "Input Policy: {}".format(policy.input_policy),
            "Result Schema: {}".format(policy.result_schema),
            "Result Profile: {}".format(policy.result_profile),
            "Candidate Manifest SHA256: {}".format(
                policy.candidate_manifest_sha256 or "none"
            ),
            "Approved Manifest SHA256: {}".format(
                policy.approved_manifest_sha256 or "none"
            ),
            "Cohort Reference SHA256: {}".format(
                policy.reference_sha256 or "none"
            ),
            "Evidence Tier: {}".format(policy.evidence_tier),
            "Use Class: {}".format(policy.use_class),
            "Clinical Use: {}".format(policy.clinical_use),
            "Maximum Recordings: {}".format(policy.maximum_recordings),
            "Run Count: 1",
            "Result Audience: self",
            "Payment: none",
            "Node Audience: {}".format(AUDIENCE),
            "Resources:",
            "- {}".format(RESOURCE),
        ]
    )


class BrainstemPersonalInsightService:
    def __init__(
        self,
        auth_service,
        personal_dao,
        metadata_dao,
        users_dao,
        upload_root,
        algorithm_image_digest,
        policy=LEGACY_POLICY,
        chain_id=11155420,
        challenge_ttl=300,
        grant_ttl=300,
        capability_ttl=60,
        result_ttl=14 * 24 * 60 * 60,
        reference_state=None,
        clock=time.time,
        nonce_factory=lambda: secrets.token_urlsafe(32),
        id_factory=lambda: uuid.uuid4().hex,
        secret_factory=lambda: secrets.token_urlsafe(32),
    ):
        self.auth_service = auth_service
        self.personal_dao = personal_dao
        self.metadata_dao = metadata_dao
        self.users_dao = users_dao
        self.upload_root = Path(upload_root)
        self.algorithm_image_digest = algorithm_image_digest
        self.policy = policy
        self.chain_id = int(chain_id)
        self.challenge_ttl = int(challenge_ttl)
        self.grant_ttl = int(grant_ttl)
        self.capability_ttl = int(capability_ttl)
        self.result_ttl = int(result_ttl)
        self.reference_state = reference_state
        self.clock = clock
        self.nonce_factory = nonce_factory
        self.id_factory = id_factory
        self.secret_factory = secret_factory
        if not DIGEST_PATTERN.fullmatch(self.algorithm_image_digest or ""):
            raise PersonalInsightError("personal_insight_disabled", 503)
        if not isinstance(self.policy, PersonalInsightPolicy):
            raise PersonalInsightError("personal_insight_disabled", 503)
        if self.policy.reference_sha256 is not None and not callable(
            self.reference_state
        ):
            raise PersonalInsightError("personal_insight_disabled", 503)
        if not 1 <= self.challenge_ttl <= 600 or not 1 <= self.grant_ttl <= 600:
            raise ValueError("Personal Insight TTL is outside the safe range")
        if not 1 <= self.capability_ttl <= 60:
            raise ValueError("Personal Insight capability TTL is outside the safe range")
        if not 1 <= self.result_ttl <= 14 * 24 * 60 * 60:
            raise ValueError("Personal Insight result TTL is outside the safe range")

    def _bound_reference_state(self, grant=None):
        reference_sha256 = (
            self.policy.reference_sha256
            if grant is None
            else grant.get("reference_sha256")
        )
        if reference_sha256 is None:
            return "current"
        try:
            state = self.reference_state(
                self.policy.analysis_id,
                reference_sha256,
                algorithm_image_digest=self.algorithm_image_digest,
                approved_manifest_sha256=self.policy.approved_manifest_sha256,
            )
        except Exception:
            state = "unavailable"
        return state if state in {"current", "superseded"} else "unavailable"

    def _require_current_reference(self):
        if self._bound_reference_state() != "current":
            raise PersonalInsightError("reference_unavailable", 410)

    def _current_user(self, user_id):
        try:
            user = self.users_dao.get_doc_by_id(user_id)
        except Exception as exc:
            raise PersonalInsightError("participant_unavailable", 401) from exc
        if (
            user.get("_id") != user_id
            or user.get("is_access_blocked")
            or not has_brainstem_data_consent(user)
        ):
            raise PersonalInsightError("participant_unavailable", 403)
        try:
            address = checksum_address(user.get("public_address"))
        except ParticipantAuthError as exc:
            raise PersonalInsightError("participant_unavailable", 401) from exc
        return user, address

    def _record_documents(self, owner) -> Iterable[Dict[str, Any]]:
        record_type = (
            "sleep" if self.policy.exporter == "sleep_baseline_latest_7" else "rest"
        )
        query = {
            "selector": {
                "created_by": owner,
                "file_type": "record",
                "record_contract_version": CONTRACT_VERSION,
                "record_type": record_type,
                "recognized_payloads": {"$elemMatch": {"$eq": "hbr_rr"}},
            },
            "fields": ["_id", "created_by", "file_path", "content_hash"],
        }
        count = 0
        for document in self.metadata_dao.iter_query(query, batch_size=500):
            count += 1
            if count > MAX_INSPECTED_RECORDS:
                raise PersonalInsightError("inspected_record_limit_exceeded", 413)
            yield document

    def _candidate(self, owner, document):
        if document.get("created_by") != owner:
            raise PersonalInsightError("record_owner_invalid")
        try:
            if self.policy.exporter == "sleep_baseline_latest_7":
                return full_night_rr_record(
                    self.upload_root,
                    owner,
                    document,
                    allowed_use="private_descriptive_self_only",
                )
            return resting_rr_record(self.upload_root, owner, document)
        except RecordExportError as exc:
            raise PersonalInsightError(exc.code, exc.status_code) from exc

    def _build(self, user_id):
        _user, owner = self._current_user(user_id)
        candidates = []
        for document in sorted(
            self._record_documents(owner), key=lambda value: value.get("_id", "")
        ):
            candidate = self._candidate(owner, document)
            if candidate is not None:
                candidates.append(candidate)
        if not candidates:
            raise PersonalInsightError("no_eligible_records", 422)

        candidates.sort(
            key=lambda value: (
                value.envelope_timestamp,
                value.content_hash,
                value.source_id,
            )
        )
        if self.policy.exporter == "resting_hrv_methods_latest_16":
            candidates = [
                candidate
                for candidate in candidates
                if 300 <= candidate.recording["durationSeconds"] <= 360
                and len(candidate.recording["rrIntervalsMs"]) >= 180
                and abs(
                    sum(candidate.recording["rrIntervalsMs"]) / 1000
                    - candidate.recording["durationSeconds"]
                )
                <= max(5, candidate.recording["durationSeconds"] * 0.1)
            ]
            if not candidates:
                raise PersonalInsightError("no_eligible_records", 422)
        if self.policy.exporter == "resting_sample_entropy_latest_4":
            candidates = [
                candidate
                for candidate in candidates
                if candidate.recording["durationSeconds"] <= 360
                and len(candidate.recording["rrIntervalsMs"]) >= 240
                and all(
                    300 <= interval <= 2000
                    for interval in candidate.recording["rrIntervalsMs"]
                )
                and abs(
                    sum(candidate.recording["rrIntervalsMs"]) / 1000
                    - candidate.recording["durationSeconds"]
                )
                <= max(5, candidate.recording["durationSeconds"] * 0.1)
            ]
            if not candidates:
                raise PersonalInsightError("no_eligible_records", 422)
        selected = candidates[-self.policy.maximum_recordings :]
        rechecked = []
        for candidate in selected:
            try:
                current = self.metadata_dao.get_doc_by_id(candidate.source_id)
            except Exception as exc:
                raise PersonalInsightError("source_deleted") from exc
            current_candidate = self._candidate(owner, current)
            if current_candidate is None or current_candidate != candidate:
                raise PersonalInsightError("source_drift")
            rechecked.append(current_candidate)
        self._current_user(user_id)
        return self._artifact(rechecked)

    def _artifact(self, candidates):
        dataset = {"schema": self.policy.input_schema}
        if self.policy.exporter in {
            "resting_rr_latest_16",
            "sleep_baseline_latest_7",
        }:
            dataset["policy"] = self.policy.input_policy
        dataset["recordings"] = [candidate.recording for candidate in candidates]
        body = canonical_json(dataset)
        if len(body) > MAX_EXPORT_BYTES:
            raise PersonalInsightError("export_byte_limit_exceeded", 413)
        return PersonalInsightArtifact(
            body=body,
            checksum=hashlib.sha256(body).hexdigest(),
            dataset=dataset,
            private_sources=tuple(
                {
                    "id": candidate.source_id,
                    "content_sha256": candidate.content_hash,
                }
                for candidate in candidates
            ),
        )

    def _exact_challenge(self, challenge, user_id, address, origin):
        fields = {
            "document_type": "brainstem_personal_insight_challenge",
            "user_id": user_id,
            "address": address,
            "origin": origin,
            "chain_id": self.chain_id,
            "purpose": self.policy.purpose,
            "scope": SCOPE,
            "insight_id": self.policy.analysis_id,
            "algorithm_image_digest": self.algorithm_image_digest,
            "input_schema": self.policy.input_schema,
            "input_policy": self.policy.input_policy,
            "result_schema": self.policy.result_schema,
            "result_profile": self.policy.result_profile,
            "candidate_manifest_sha256": self.policy.candidate_manifest_sha256,
            "approved_manifest_sha256": self.policy.approved_manifest_sha256,
            "reference_sha256": self.policy.reference_sha256,
            "evidence_tier": self.policy.evidence_tier,
            "use_class": self.policy.use_class,
            "clinical_use": self.policy.clinical_use,
            "maximum_recordings": self.policy.maximum_recordings,
            "run_count": 1,
            "result_audience": "self",
            "payment": "none",
            "node_audience": AUDIENCE,
        }
        if any(challenge.get(key) != value for key, value in fields.items()):
            raise PersonalInsightError("challenge_unavailable", 401)
        challenge_id = challenge.get("challenge_id")
        nonce = challenge.get("nonce")
        issued_at = challenge.get("issued_at")
        expires_at = challenge.get("expires_at")
        if (
            not isinstance(challenge_id, str)
            or not IDENTIFIER.fullmatch(challenge_id)
            or not isinstance(nonce, str)
            or not SESSION_SECRET.fullmatch(nonce)
            or not isinstance(issued_at, int)
            or not isinstance(expires_at, int)
            or expires_at - issued_at != self.challenge_ttl
        ):
            raise PersonalInsightError("challenge_unavailable", 401)
        expected_message = _message(
            self.policy,
            origin,
            address,
            self.chain_id,
            nonce,
            challenge_id,
            issued_at,
            expires_at,
            self.algorithm_image_digest,
        )
        message = challenge.get("message")
        if not isinstance(message, str) or not hmac.compare_digest(
            message, expected_message
        ):
            raise PersonalInsightError("challenge_unavailable", 401)
        return message

    def create_challenge(self, participant_token, origin):
        self._require_current_reference()
        _session_id, _session, session_user = self.auth_service.authenticate(
            participant_token, origin
        )
        user, address = self._current_user(session_user["_id"])
        self._build(user["_id"])
        now = int(self.clock())
        challenge_id = self.id_factory()
        nonce = self.nonce_factory()
        if (
            not isinstance(challenge_id, str)
            or not IDENTIFIER.fullmatch(challenge_id)
            or not isinstance(nonce, str)
            or not SESSION_SECRET.fullmatch(nonce)
        ):
            raise RuntimeError("Invalid Personal Insight challenge credential")
        expires_at = now + self.challenge_ttl
        message = _message(
            self.policy,
            origin,
            address,
            self.chain_id,
            nonce,
            challenge_id,
            now,
            expires_at,
            self.algorithm_image_digest,
        )
        challenge = {
            "document_type": "brainstem_personal_insight_challenge",
            "challenge_id": challenge_id,
            "user_id": user["_id"],
            "address": address,
            "origin": origin,
            "chain_id": self.chain_id,
            "nonce": nonce,
            "purpose": self.policy.purpose,
            "scope": SCOPE,
            "insight_id": self.policy.analysis_id,
            "algorithm_image_digest": self.algorithm_image_digest,
            "input_schema": self.policy.input_schema,
            "input_policy": self.policy.input_policy,
            "result_schema": self.policy.result_schema,
            "result_profile": self.policy.result_profile,
            "candidate_manifest_sha256": self.policy.candidate_manifest_sha256,
            "approved_manifest_sha256": self.policy.approved_manifest_sha256,
            "reference_sha256": self.policy.reference_sha256,
            "evidence_tier": self.policy.evidence_tier,
            "use_class": self.policy.use_class,
            "clinical_use": self.policy.clinical_use,
            "maximum_recordings": self.policy.maximum_recordings,
            "run_count": 1,
            "result_audience": "self",
            "payment": "none",
            "node_audience": AUDIENCE,
            "message": message,
            "issued_at": now,
            "expires_at": expires_at,
            "consumed_at": None,
        }
        challenge = self.personal_dao.create_or_get_challenge(
            _slot(origin, user["_id"], self.policy.analysis_id), challenge, now
        )
        return {
            "challengeId": challenge["challenge_id"],
            "message": challenge["message"],
            "expiresAt": rfc3339(challenge["expires_at"]),
            "chainId": self.chain_id,
            "method": "personal_sign",
        }

    def exchange(self, participant_token, origin, challenge_id, signature):
        self._require_current_reference()
        _session_id, _session, session_user = self.auth_service.authenticate(
            participant_token, origin
        )
        user, address = self._current_user(session_user["_id"])
        if not isinstance(challenge_id, str) or not IDENTIFIER.fullmatch(challenge_id):
            raise PersonalInsightError("challenge_unavailable")
        slot = _slot(origin, user["_id"], self.policy.analysis_id)
        try:
            challenge = self.personal_dao.get_challenge(slot)
        except PersonalInsightStateError as exc:
            raise PersonalInsightError("challenge_unavailable", 401) from exc
        now = int(self.clock())
        if challenge.get("expires_at", 0) <= now:
            raise PersonalInsightError("challenge_expired", 410)
        if challenge.get("challenge_id") != challenge_id:
            raise PersonalInsightError("challenge_unavailable", 401)
        if challenge.get("consumed_at") is not None:
            raise PersonalInsightError("challenge_used", 409)
        message = self._exact_challenge(
            challenge, user["_id"], address, origin
        )
        try:
            verify_wallet_signature(message, signature, address)
        except ParticipantAuthError as exc:
            raise PersonalInsightError("signature_invalid", exc.status_code) from exc
        try:
            self.personal_dao.consume_challenge(slot, challenge_id, now)
        except PersonalInsightStateError as exc:
            status = 410 if "expired" in str(exc).lower() else 409
            raise PersonalInsightError("challenge_unavailable", status) from exc

        grant_id = self.id_factory()
        secret = self.secret_factory()
        if (
            not isinstance(grant_id, str)
            or not IDENTIFIER.fullmatch(grant_id)
            or not isinstance(secret, str)
            or not SESSION_SECRET.fullmatch(secret)
        ):
            raise RuntimeError("Invalid Personal Insight grant credential")
        token = "{}.{}".format(grant_id, secret)
        expires_at = now + self.grant_ttl
        self.personal_dao.save_grant(
            grant_id,
            {
                "document_type": "brainstem_personal_insight_grant",
                "user_id": user["_id"],
                "token_sha256": _sha256(token),
                "challenge_id_sha256": _sha256(challenge_id),
                "message_sha256": _sha256(message),
                "signature_sha256": _sha256(signature),
                "origin": origin,
                "scope": SCOPE,
                "purpose": self.policy.purpose,
                "insight_id": self.policy.analysis_id,
                "algorithm_image_digest": self.algorithm_image_digest,
                "input_schema": self.policy.input_schema,
                "input_policy": self.policy.input_policy,
                "result_schema": self.policy.result_schema,
                "result_profile": self.policy.result_profile,
                "candidate_manifest_sha256": self.policy.candidate_manifest_sha256,
                "approved_manifest_sha256": self.policy.approved_manifest_sha256,
                "reference_sha256": self.policy.reference_sha256,
                "evidence_tier": self.policy.evidence_tier,
                "use_class": self.policy.use_class,
                "clinical_use": self.policy.clinical_use,
                "maximum_recordings": self.policy.maximum_recordings,
                "run_count": 1,
                "result_audience": "self",
                "payment": "none",
                "node_audience": AUDIENCE,
                "state": "approved",
                "issued_at": now,
                "expires_at": expires_at,
                "job_id_sha256": None,
                "run_id_sha256": None,
                "history_id": None,
                "claimed_at": None,
                "fetch_started_at": None,
                "fetched_at": None,
                "result_sha256": None,
                "result_expires_at": None,
                "completed_at": None,
            },
        )
        return {
            "grant": token,
            "expiresAt": rfc3339(expires_at),
            "scope": SCOPE,
        }

    @staticmethod
    def _grant_parts(token):
        if not isinstance(token, str) or token.count(".") != 1:
            raise PersonalInsightError("grant_unavailable", 401)
        grant_id, secret = token.split(".", 1)
        if not IDENTIFIER.fullmatch(grant_id) or not SESSION_SECRET.fullmatch(secret):
            raise PersonalInsightError("grant_unavailable", 401)
        return grant_id, _sha256(token)

    @staticmethod
    def _run_hash(run_id):
        if not isinstance(run_id, str) or not RUN_ID_PATTERN.fullmatch(run_id):
            raise PersonalInsightError("run_invalid")
        return _sha256(run_id)

    def _exact_grant(self, grant, historical_reference=False):
        fields = {
            "document_type": "brainstem_personal_insight_grant",
            "scope": SCOPE,
            "purpose": self.policy.purpose,
            "insight_id": self.policy.analysis_id,
            "algorithm_image_digest": self.algorithm_image_digest,
            "input_schema": self.policy.input_schema,
            "input_policy": self.policy.input_policy,
            "result_schema": self.policy.result_schema,
            "result_profile": self.policy.result_profile,
            "candidate_manifest_sha256": self.policy.candidate_manifest_sha256,
            "approved_manifest_sha256": self.policy.approved_manifest_sha256,
            "reference_sha256": self.policy.reference_sha256,
            "evidence_tier": self.policy.evidence_tier,
            "use_class": self.policy.use_class,
            "clinical_use": self.policy.clinical_use,
            "maximum_recordings": self.policy.maximum_recordings,
            "run_count": 1,
            "result_audience": "self",
            "payment": "none",
            "node_audience": AUDIENCE,
        }
        if historical_reference:
            fields.pop("reference_sha256")
        if any(grant.get(key) != value for key, value in fields.items()):
            raise PersonalInsightError("grant_unavailable", 401)
        historical_value = grant.get("reference_sha256")
        if historical_reference and historical_value is not None and (
            not isinstance(historical_value, str)
            or not SHA256_PATTERN.fullmatch(historical_value)
        ):
            raise PersonalInsightError("grant_unavailable", 401)
        for field in (
            "token_sha256",
            "challenge_id_sha256",
            "message_sha256",
            "signature_sha256",
        ):
            value = grant.get(field)
            if (
                not isinstance(value, str)
                or len(value) != 64
                or any(character not in "0123456789abcdef" for character in value)
            ):
                raise PersonalInsightError("grant_unavailable", 401)
        if (
            not isinstance(grant.get("user_id"), str)
            or not grant["user_id"]
            or not isinstance(grant.get("origin"), str)
            or not isinstance(grant.get("issued_at"), int)
            or not isinstance(grant.get("expires_at"), int)
            or grant["expires_at"] - grant["issued_at"] != self.grant_ttl
            or grant.get("state")
            not in {
                "approved",
                "claimed",
                "fetching",
                "fetched",
                "complete",
                "failed",
            }
        ):
            raise PersonalInsightError("grant_unavailable", 401)
        state = grant["state"]
        bound_hashes = ("job_id_sha256", "run_id_sha256")
        if state == "approved":
            if (
                any(grant.get(field) is not None for field in bound_hashes)
                or grant.get("history_id") is not None
            ):
                raise PersonalInsightError("grant_unavailable", 401)
        else:
            if any(
                not isinstance(grant.get(field), str)
                or not SHA256_PATTERN.fullmatch(grant[field])
                for field in bound_hashes
            ) or (
                grant.get("history_id") is not None
                and not HISTORY_ID_PATTERN.fullmatch(grant["history_id"])
            ):
                raise PersonalInsightError("grant_unavailable", 401)
        if state == "complete":
            if (
                not isinstance(grant.get("result_sha256"), str)
                or not SHA256_PATTERN.fullmatch(grant["result_sha256"])
                or not isinstance(grant.get("result_expires_at"), int)
            ):
                raise PersonalInsightError("grant_unavailable", 401)
        elif (
            grant.get("result_sha256") is not None
            or grant.get("result_expires_at") is not None
        ):
            raise PersonalInsightError("grant_unavailable", 401)
        return grant

    @staticmethod
    def _grant_id(grant):
        prefix = "personal_insight_grant:"
        document_id = grant.get("_id")
        if (
            not isinstance(document_id, str)
            or not document_id.startswith(prefix)
            or not IDENTIFIER.fullmatch(document_id[len(prefix) :])
        ):
            raise PersonalInsightError("grant_unavailable", 401)
        return document_id[len(prefix) :]

    @staticmethod
    def _job_hash(job_id):
        if not isinstance(job_id, str) or not JOB_ID_PATTERN.fullmatch(job_id):
            raise PersonalInsightError("job_invalid")
        return _sha256(job_id)

    def claim(self, grant_token, job_id, run_id):
        self._require_current_reference()
        grant_id, token_hash = self._grant_parts(grant_token)
        job_hash = self._job_hash(job_id)
        run_hash = self._run_hash(run_id)
        history_id = _sha256(
            "brainstem-personal-history\0{}".format(grant_token)
        )
        now = int(self.clock())
        try:
            self._exact_grant(self.personal_dao.get_grant(grant_id))
            grant = self.personal_dao.claim_grant(
                grant_id,
                token_hash,
                job_hash,
                run_hash,
                history_id,
                now,
            )
        except PersonalInsightStateError as exc:
            status = 410 if "expired" in str(exc).lower() else 409
            raise PersonalInsightError("grant_unavailable", status) from exc
        self._exact_grant(grant)
        self._build(grant["user_id"])
        return {
            "status": "claimed",
            "historyId": grant["history_id"],
            "expiresAt": rfc3339(grant["expires_at"]),
            "analysisId": self.policy.analysis_id,
            "algorithmVersion": self.policy.algorithm_version,
            "algorithmImageDigest": self.algorithm_image_digest,
            "inputSchema": self.policy.input_schema,
            "inputPolicy": self.policy.input_policy,
            "resultSchema": self.policy.result_schema,
            "resultProfile": self.policy.result_profile,
            "candidateManifestSha256": self.policy.candidate_manifest_sha256,
            "approvedManifestSha256": self.policy.approved_manifest_sha256,
            "referenceSha256": self.policy.reference_sha256,
            "evidenceTier": self.policy.evidence_tier,
            "useClass": self.policy.use_class,
            "clinicalUse": self.policy.clinical_use,
            "maximumRecordings": self.policy.maximum_recordings,
            "audience": AUDIENCE,
        }

    def fetch(self, grant_token, job_id):
        self._require_current_reference()
        grant_id, token_hash = self._grant_parts(grant_token)
        job_hash = self._job_hash(job_id)
        now = int(self.clock())
        try:
            self._exact_grant(self.personal_dao.get_grant(grant_id))
            grant = self.personal_dao.begin_fetch(
                grant_id, token_hash, job_hash, now
            )
            self._exact_grant(grant)
            artifact = self._build(grant["user_id"])
            if grant.get("expires_at", 0) <= int(self.clock()):
                raise PersonalInsightError("grant_expired", 410)
            self.personal_dao.complete_fetch(
                grant_id,
                job_hash,
                artifact.checksum,
                len(artifact.body),
                list(artifact.private_sources),
                int(self.clock()),
            )
            return artifact
        except PersonalInsightError as exc:
            try:
                self.personal_dao.fail_fetch(
                    grant_id, job_hash, exc.code, int(self.clock())
                )
            except Exception:
                pass
            raise
        except PersonalInsightStateError as exc:
            status = 410 if "expired" in str(exc).lower() else 409
            raise PersonalInsightError("dataset_unavailable", status) from exc

    def _verify_fetched_sources(self, grant):
        _user, owner = self._current_user(grant["user_id"])
        sources = grant.get("source_records")
        if (
            not isinstance(sources, list)
            or not 1 <= len(sources) <= self.policy.maximum_recordings
        ):
            raise PersonalInsightError("source_drift", 410)
        candidates = []
        for source in sources:
            if (
                not isinstance(source, dict)
                or set(source) != {"id", "content_sha256"}
                or not isinstance(source.get("id"), str)
                or not isinstance(source.get("content_sha256"), str)
                or not SHA256_PATTERN.fullmatch(source["content_sha256"])
            ):
                raise PersonalInsightError("source_drift", 410)
            try:
                document = self.metadata_dao.get_doc_by_id(source["id"])
            except Exception as exc:
                raise PersonalInsightError("source_deleted", 410) from exc
            candidate = self._candidate(owner, document)
            if (
                candidate is None
                or candidate.source_id != source["id"]
                or not hmac.compare_digest(
                    candidate.content_hash, source["content_sha256"]
                )
            ):
                raise PersonalInsightError("source_drift", 410)
            candidates.append(candidate)
        self._current_user(grant["user_id"])
        artifact = self._artifact(candidates)
        expected_sources = list(artifact.private_sources)
        if (
            grant.get("dataset_sha256") != artifact.checksum
            or grant.get("dataset_byte_count") != len(artifact.body)
            or grant.get("source_records") != expected_sources
        ):
            raise PersonalInsightError("source_drift", 410)
        return artifact

    def complete(self, grant_token, job_id, run_id, result_sha256):
        self._require_current_reference()
        grant_id, token_hash = self._grant_parts(grant_token)
        job_hash = self._job_hash(job_id)
        run_hash = self._run_hash(run_id)
        if (
            not isinstance(result_sha256, str)
            or not SHA256_PATTERN.fullmatch(result_sha256)
        ):
            raise PersonalInsightError("result_invalid")
        now = int(self.clock())
        try:
            grant = self._exact_grant(self.personal_dao.get_grant(grant_id))
            if (
                not _matches(grant.get("token_sha256"), token_hash)
                or not _matches(grant.get("job_id_sha256"), job_hash)
                or not _matches(grant.get("run_id_sha256"), run_hash)
            ):
                raise PersonalInsightError("run_unavailable", 401)
            self._verify_fetched_sources(grant)
            grant = self.personal_dao.complete_run(
                grant_id,
                token_hash,
                job_hash,
                run_hash,
                result_sha256,
                now + self.result_ttl,
                now,
            )
        except PersonalInsightStateError as exc:
            raise PersonalInsightError("run_unavailable", 409) from exc
        self._exact_grant(grant)
        return {
            "status": "complete",
            "resultExpiresAt": rfc3339(grant["result_expires_at"]),
        }

    def revalidate(self, grant_token, job_id, run_id):
        self._require_current_reference()
        grant_id, token_hash = self._grant_parts(grant_token)
        job_hash = self._job_hash(job_id)
        run_hash = self._run_hash(run_id)
        try:
            grant = self._exact_grant(self.personal_dao.get_grant(grant_id))
        except PersonalInsightStateError as exc:
            raise PersonalInsightError("run_unavailable", 401) from exc
        if (
            grant.get("state") != "complete"
            or not _matches(grant.get("token_sha256"), token_hash)
            or not _matches(grant.get("job_id_sha256"), job_hash)
            or not _matches(grant.get("run_id_sha256"), run_hash)
        ):
            raise PersonalInsightError("run_unavailable", 401)
        if grant.get("result_expires_at", 0) <= int(self.clock()):
            raise PersonalInsightError("run_revoked", 410)
        try:
            self._verify_fetched_sources(grant)
        except PersonalInsightError as exc:
            raise PersonalInsightError("run_revoked", 410) from exc
        return {"status": "authorized", "jobId": job_id, "runId": run_id}

    def revalidate_history(self, history_id):
        if (
            not isinstance(history_id, str)
            or not HISTORY_ID_PATTERN.fullmatch(history_id)
        ):
            raise PersonalInsightError("run_revoked", 410)
        try:
            grant = self._exact_grant(
                self.personal_dao.get_history(history_id),
                historical_reference=True,
            )
        except PersonalInsightStateError as exc:
            raise PersonalInsightError("run_revoked", 410) from exc
        if (
            grant.get("history_id") != history_id
            or grant.get("state") != "complete"
            or grant.get("result_expires_at", 0) <= int(self.clock())
        ):
            raise PersonalInsightError("run_revoked", 410)
        if self._bound_reference_state(grant) == "unavailable":
            raise PersonalInsightError("run_revoked", 410)
        try:
            self._verify_fetched_sources(grant)
        except PersonalInsightError as exc:
            raise PersonalInsightError("run_revoked", 410) from exc
        return {"status": "authorized", "historyId": history_id}

    @staticmethod
    def _coarse_timestamp(value):
        if not isinstance(value, int):
            return None
        return rfc3339(value - (value % (24 * 60 * 60)))

    def _history_projection(self, grant, now, current_sources=None):
        state = grant["state"]
        correction_state = "current"
        if state == "complete":
            if grant.get("result_expires_at", 0) <= now:
                state = "expired"
            else:
                try:
                    self._verify_fetched_sources(grant)
                except PersonalInsightError:
                    state = "revoked"
                    correction_state = "revoked"
            reference_state = self._bound_reference_state(grant)
            if reference_state == "superseded":
                correction_state = "superseded"
            elif reference_state == "unavailable":
                state = "revoked"
                correction_state = "unavailable"
        elif state == "failed":
            state = "failed"
        else:
            state = "pending"
        return {
            "historyId": grant["history_id"],
            "analysisId": self.policy.analysis_id,
            "algorithmVersion": self.policy.algorithm_version,
            "algorithmImageDigest": self.algorithm_image_digest,
            "status": state,
            "createdAt": self._coarse_timestamp(grant["issued_at"]),
            "completedAt": self._coarse_timestamp(grant.get("completed_at")),
            "expiresAt": self._coarse_timestamp(
                grant.get("result_expires_at")
            ),
            "correctionState": correction_state,
            "updateAvailable": (
                state == "complete"
                and current_sources is not None
                and grant.get("source_records") != current_sources
            ),
        }

    def history(self, participant_token, origin, limit=20):
        if not isinstance(limit, int) or not 1 <= limit <= MAX_HISTORY_ENTRIES:
            raise PersonalInsightError("history_limit_invalid")
        _session_id, _session, session_user = self.auth_service.authenticate(
            participant_token, origin
        )
        user, _address = self._current_user(session_user["_id"])
        documents = self.personal_dao.list_history(
            user["_id"], origin, MAX_HISTORY_SCAN + 1
        )
        if len(documents) > MAX_HISTORY_SCAN:
            raise PersonalInsightError("history_limit_exceeded", 413)
        grants = []
        for document in documents:
            if document.get("insight_id") != self.policy.analysis_id:
                continue
            grant = self._exact_grant(document, historical_reference=True)
            if (
                grant.get("user_id") != user["_id"]
                or grant.get("origin") != origin
            ):
                raise PersonalInsightError("history_unavailable", 404)
            grants.append(grant)
        grants.sort(
            key=lambda value: (value["issued_at"], value["history_id"]),
            reverse=True,
        )
        now = int(self.clock())
        current_sources = None
        if any(
            grant["state"] == "complete"
            and grant.get("result_expires_at", 0) > now
            for grant in grants[:limit]
        ):
            try:
                current_sources = list(self._build(user["_id"]).private_sources)
            except PersonalInsightError:
                pass
        return [
            self._history_projection(grant, now, current_sources)
            for grant in grants[:limit]
        ]

    def _history_grant(self, participant_token, origin, history_id):
        if (
            not isinstance(history_id, str)
            or not HISTORY_ID_PATTERN.fullmatch(history_id)
        ):
            raise PersonalInsightError("history_unavailable", 404)
        _session_id, _session, session_user = self.auth_service.authenticate(
            participant_token, origin
        )
        user, _address = self._current_user(session_user["_id"])
        try:
            grant = self._exact_grant(
                self.personal_dao.get_history(history_id),
                historical_reference=True,
            )
        except PersonalInsightStateError as exc:
            raise PersonalInsightError("history_unavailable", 404) from exc
        if (
            grant.get("history_id") != history_id
            or grant.get("user_id") != user["_id"]
            or grant.get("origin") != origin
        ):
            raise PersonalInsightError("history_unavailable", 404)
        return grant

    def _save_capability(
        self,
        grant_id,
        run_hash,
        action,
        now,
        history_id=None,
    ):
        capability_id = self.id_factory()
        secret = self.secret_factory()
        if (
            not isinstance(capability_id, str)
            or not IDENTIFIER.fullmatch(capability_id)
            or not isinstance(secret, str)
            or not SESSION_SECRET.fullmatch(secret)
        ):
            raise RuntimeError("Invalid Personal Insight access credential")
        capability = "{}.{}".format(capability_id, secret)
        expires_at = now + self.capability_ttl
        document = {
            "document_type": "brainstem_personal_insight_capability",
            "grant_id": grant_id,
            "token_sha256": _sha256(capability),
            "run_id_sha256": run_hash,
            "action": action,
            "issued_at": now,
            "expires_at": expires_at,
            "consumed_at": None,
        }
        if history_id is not None:
            document["history_id"] = history_id
        self.personal_dao.save_capability(capability_id, document)
        return capability, expires_at

    def issue_access(
        self,
        participant_token,
        origin,
        grant_token,
        run_id,
        action,
    ):
        self._require_current_reference()
        if action not in ACCESS_ACTIONS:
            raise PersonalInsightError("action_invalid")
        _session_id, _session, session_user = self.auth_service.authenticate(
            participant_token, origin
        )
        user, _address = self._current_user(session_user["_id"])
        grant_id, token_hash = self._grant_parts(grant_token)
        run_hash = self._run_hash(run_id)
        try:
            grant = self._exact_grant(self.personal_dao.get_grant(grant_id))
        except PersonalInsightStateError as exc:
            raise PersonalInsightError("run_unavailable", 404) from exc
        if (
            grant.get("user_id") != user["_id"]
            or grant.get("origin") != origin
            or not _matches(grant.get("token_sha256"), token_hash)
            or not _matches(grant.get("run_id_sha256"), run_hash)
            or grant.get("state") not in {"claimed", "fetching", "fetched", "complete"}
            or (action == "result" and grant.get("state") != "complete")
        ):
            raise PersonalInsightError("run_unavailable", 404)
        now = int(self.clock())
        if (
            grant.get("state") == "complete"
            and grant.get("result_expires_at", 0) <= now
        ):
            raise PersonalInsightError("run_expired", 410)
        if grant.get("state") in {"fetched", "complete"}:
            self._verify_fetched_sources(grant)
        else:
            self._build(grant["user_id"])

        capability, expires_at = self._save_capability(
            grant_id, run_hash, action, now
        )
        return {
            "capability": capability,
            "action": action,
            "runId": run_id,
            "expiresAt": rfc3339(expires_at),
        }

    def issue_history_access(
        self,
        participant_token,
        origin,
        history_id,
        action,
    ):
        if action not in ACCESS_ACTIONS:
            raise PersonalInsightError("action_invalid")
        grant = self._history_grant(
            participant_token, origin, history_id
        )
        if self._bound_reference_state(grant) == "unavailable":
            raise PersonalInsightError("history_unavailable", 410)
        if (
            grant.get("state")
            not in {"claimed", "fetching", "fetched", "complete"}
            or (action == "result" and grant.get("state") != "complete")
        ):
            raise PersonalInsightError("history_unavailable", 404)
        now = int(self.clock())
        if (
            grant.get("state") == "complete"
            and grant.get("result_expires_at", 0) <= now
        ):
            raise PersonalInsightError("run_expired", 410)
        if grant.get("state") in {"fetched", "complete"}:
            self._verify_fetched_sources(grant)
        else:
            self._build(grant["user_id"])
        capability, expires_at = self._save_capability(
            self._grant_id(grant),
            grant["run_id_sha256"],
            action,
            now,
            history_id=history_id,
        )
        return {
            "capability": capability,
            "action": action,
            "historyId": history_id,
            "expiresAt": rfc3339(expires_at),
        }

    def consume_access(self, capability, run_id, action):
        self._require_current_reference()
        if action not in ACCESS_ACTIONS:
            raise PersonalInsightError("action_invalid")
        capability_id, token_hash = self._grant_parts(capability)
        run_hash = self._run_hash(run_id)
        now = int(self.clock())
        try:
            document = self.personal_dao.consume_capability(
                capability_id, token_hash, run_hash, action, now
            )
            grant = self._exact_grant(
                self.personal_dao.get_grant(document["grant_id"])
            )
        except (KeyError, PersonalInsightStateError) as exc:
            status = 410 if "expired" in str(exc).lower() else 409
            raise PersonalInsightError("capability_unavailable", status) from exc
        if (
            not _matches(grant.get("run_id_sha256"), run_hash)
            or grant.get("state") not in {"claimed", "fetching", "fetched", "complete"}
            or (action == "result" and grant.get("state") != "complete")
        ):
            raise PersonalInsightError("capability_unavailable", 409)
        if (
            grant.get("state") == "complete"
            and grant.get("result_expires_at", 0) <= now
        ):
            raise PersonalInsightError("run_expired", 410)
        if grant.get("state") in {"fetched", "complete"}:
            self._verify_fetched_sources(grant)
        else:
            self._build(grant["user_id"])
        return {
            "status": "authorized",
            "action": action,
            "runId": run_id,
            "resultSha256": (
                grant["result_sha256"] if action == "result" else None
            ),
        }

    def consume_history_access(self, capability, history_id, action):
        if action not in ACCESS_ACTIONS:
            raise PersonalInsightError("action_invalid")
        if (
            not isinstance(history_id, str)
            or not HISTORY_ID_PATTERN.fullmatch(history_id)
        ):
            raise PersonalInsightError("capability_unavailable", 409)
        capability_id, token_hash = self._grant_parts(capability)
        now = int(self.clock())
        try:
            document = self.personal_dao.consume_history_capability(
                capability_id, token_hash, history_id, action, now
            )
            grant = self._exact_grant(
                self.personal_dao.get_grant(document["grant_id"]),
                historical_reference=True,
            )
        except (KeyError, PersonalInsightStateError) as exc:
            status = 410 if "expired" in str(exc).lower() else 409
            raise PersonalInsightError("capability_unavailable", status) from exc
        if self._bound_reference_state(grant) == "unavailable":
            raise PersonalInsightError("capability_unavailable", 410)
        if (
            grant.get("history_id") != history_id
            or grant.get("state")
            not in {"claimed", "fetching", "fetched", "complete"}
            or (action == "result" and grant.get("state") != "complete")
        ):
            raise PersonalInsightError("capability_unavailable", 409)
        if (
            grant.get("state") == "complete"
            and grant.get("result_expires_at", 0) <= now
        ):
            raise PersonalInsightError("run_expired", 410)
        if grant.get("state") in {"fetched", "complete"}:
            self._verify_fetched_sources(grant)
        else:
            self._build(grant["user_id"])
        return {
            "status": "authorized",
            "action": action,
            "historyId": history_id,
            "resultSha256": (
                grant["result_sha256"] if action == "result" else None
            ),
        }
