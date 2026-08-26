from copy import deepcopy
from datetime import datetime
import hashlib
import json
import re
from typing import Any, Dict, Iterable

from eth_account import Account
from eth_account.messages import encode_defunct

from commands.dataunions.brainstem.consent import has_brainstem_data_consent
from commands.dataunions.brainstem.cohort_release import (
    CohortReleaseError,
    CohortReleaseService,
)
from dao.base_dao import DBResultError
from models.metadata.metadata_models import Source
from models.rewards.rewards_model import RewardStatus


VALUE_POLICY = "brainstem.equal-cohort-contribution/v1"
RECEIPT_SCHEMA = "brainstem.compute-receipt/v1"
COMMITMENT_SCHEMA = "brainstem.participant-value-commitment/v1"
RESULT_SCHEMA = "brainstem.c2d-result/v1"
INPUT_SCHEMA = "brainstem.private-rr-cohort/v1"
INPUT_POLICY = "brainstem.resting-rr/v1"
DOCUMENT_TYPE_MANIFEST = "brainstem_c2d_contribution_manifest"
DOCUMENT_TYPE_ENTITLEMENT = "brainstem_value_entitlement"
DOCUMENT_TYPE_COMMIT = "brainstem_value_commit"
RECEIPT_KEYS = {
    "schema",
    "jobIdHash",
    "inputSha256",
    "resultSha256",
    "resultSchema",
    "resultStatus",
    "algorithmImageDigest",
    "completedAt",
}
HEX_64 = re.compile(r"^[0-9a-f]{64}$")
IMAGE_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
ADDRESS = re.compile(r"^0x[0-9a-fA-F]{40}$")
SIGNATURE = re.compile(r"^0x[0-9a-fA-F]{130}$")
MAX_CONTRIBUTORS = 1_000
MAX_RECORDS_PER_CONTRIBUTOR = 16
MAX_AMOUNT = 1_000


class ValueCommitError(RuntimeError):
    def __init__(self, code: str, status_code: int = 422):
        super().__init__(code)
        self.code = code
        self.status_code = status_code


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _parse_timestamp(value: Any) -> None:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValueCommitError("compute_receipt_invalid", 400)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueCommitError("compute_receipt_invalid", 400) from exc
    if parsed.tzinfo is None:
        raise ValueCommitError("compute_receipt_invalid", 400)


def _stored_document(document: Dict[str, Any]) -> Dict[str, Any]:
    return {
        key: deepcopy(value)
        for key, value in document.items()
        if key not in {"_id", "_rev"}
    }


def _save_exactly_once(dao, doc_id: str, document: Dict[str, Any]) -> Dict[str, Any]:
    exists, current = dao.get_if_exists(doc_id)
    if exists:
        if _stored_document(current) != document:
            raise ValueCommitError("value_state_conflict", 409)
        return current
    try:
        dao.save(doc_id, document)
    except DBResultError:
        exists, current = dao.get_if_exists(doc_id)
        if not exists or _stored_document(current) != document:
            raise
        return current
    return {"_id": doc_id, **deepcopy(document)}


def _identifier(value: Any, field: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 256
        or any(character in value for character in "\r\n\0")
    ):
        raise ValueCommitError(f"{field}_invalid")
    return value


def _normalize_contributors(contributors: Iterable[Dict[str, Any]]) -> list:
    normalized = []
    for contributor in contributors:
        if not isinstance(contributor, dict) or set(contributor) != {
            "internal_user_id",
            "public_address",
            "record_owner",
            "records",
        }:
            raise ValueCommitError("contribution_manifest_invalid")
        records = contributor["records"]
        if (
            not isinstance(records, (list, tuple))
            or not 1 <= len(records) <= MAX_RECORDS_PER_CONTRIBUTOR
        ):
            raise ValueCommitError("contribution_manifest_invalid")
        normalized_records = []
        for record in records:
            if (
                not isinstance(record, dict)
                or set(record) != {"id", "content_sha256"}
                or not HEX_64.fullmatch(record.get("content_sha256", ""))
            ):
                raise ValueCommitError("contribution_manifest_invalid")
            normalized_records.append({
                "id": _identifier(record["id"], "record_id"),
                "content_sha256": record["content_sha256"],
            })
        normalized_records.sort(key=lambda item: item["id"])
        if len({record["id"] for record in normalized_records}) != len(
            normalized_records
        ):
            raise ValueCommitError("contribution_manifest_invalid")
        normalized.append({
            "internal_user_id": _identifier(
                contributor["internal_user_id"], "internal_user_id"
            ),
            "public_address": _identifier(
                contributor["public_address"], "public_address"
            ),
            "record_owner": _identifier(
                contributor["record_owner"], "record_owner"
            ),
            "records": normalized_records,
        })
    if not 1 <= len(normalized) <= MAX_CONTRIBUTORS:
        raise ValueCommitError("contribution_manifest_invalid")
    normalized.sort(key=lambda item: item["internal_user_id"])
    if len({item["internal_user_id"] for item in normalized}) != len(normalized):
        raise ValueCommitError("contribution_manifest_invalid")
    return normalized


class BrainstemValueService:
    def __init__(
        self,
        rewards_dao,
        metadata_dao,
        users_dao,
        release_dao,
        consent_version: str,
        amount: int,
        approved_algorithm_digest: str,
        expected_node_signer: str,
        signing_private_key: str,
    ):
        if (
            not isinstance(amount, int)
            or isinstance(amount, bool)
            or not 1 <= amount <= MAX_AMOUNT
            or not IMAGE_DIGEST.fullmatch(approved_algorithm_digest or "")
            or not ADDRESS.fullmatch(expected_node_signer or "")
        ):
            raise ValueCommitError("value_configuration_invalid", 503)
        try:
            signing_account = Account.from_key(signing_private_key)
        except Exception as exc:
            raise ValueCommitError("value_configuration_invalid", 503) from exc
        self.rewards_dao = rewards_dao
        self.metadata_dao = metadata_dao
        self.users_dao = users_dao
        self.release_dao = release_dao
        self.consent_version = consent_version
        self.amount = amount
        self.approved_algorithm_digest = approved_algorithm_digest
        self.expected_node_signer = expected_node_signer.lower()
        self.signing_account = signing_account

    @staticmethod
    def manifest_id(job_id_hash: str) -> str:
        return f"brainstem-c2d-value:{job_id_hash}"

    def record_export(
        self,
        job_id: str,
        release_id: str,
        input_sha256: str,
        input_schema: str,
        input_policy: str,
        contributors: Iterable[Dict[str, Any]],
    ) -> str:
        if (
            not isinstance(job_id, str)
            or not HEX_64.fullmatch(job_id)
            or not isinstance(release_id, str)
            or not HEX_64.fullmatch(release_id)
            or not HEX_64.fullmatch(input_sha256 or "")
            or input_schema != INPUT_SCHEMA
            or input_policy != INPUT_POLICY
        ):
            raise ValueCommitError("contribution_manifest_invalid")
        job_id_hash = hashlib.sha256(job_id.encode("utf-8")).hexdigest()
        manifest = {
            "document_type": DOCUMENT_TYPE_MANIFEST,
            "job_id_hash": job_id_hash,
            "release_id": release_id,
            "release_id_hash": hashlib.sha256(
                release_id.encode("utf-8")
            ).hexdigest(),
            "input_sha256": input_sha256,
            "schema": input_schema,
            "policy": input_policy,
            "value_policy": VALUE_POLICY,
            "amount": self.amount,
            "algorithm_image_digest": self.approved_algorithm_digest,
            "contributors": _normalize_contributors(contributors),
            "status": "pending",
        }
        doc_id = self.manifest_id(job_id_hash)
        _save_exactly_once(self.rewards_dao, doc_id, manifest)
        return doc_id

    def _validate_receipt(
        self, receipt: Any, signature: Any
    ) -> tuple[Dict[str, Any], str]:
        if not isinstance(receipt, dict) or set(receipt) != RECEIPT_KEYS:
            raise ValueCommitError("compute_receipt_invalid", 400)
        if (
            receipt.get("schema") != RECEIPT_SCHEMA
            or not HEX_64.fullmatch(receipt.get("jobIdHash", ""))
            or not HEX_64.fullmatch(receipt.get("inputSha256", ""))
            or not HEX_64.fullmatch(receipt.get("resultSha256", ""))
            or receipt.get("resultSchema") != RESULT_SCHEMA
            or receipt.get("resultStatus") not in {"complete", "insufficient_data"}
            or not IMAGE_DIGEST.fullmatch(receipt.get("algorithmImageDigest", ""))
            or not isinstance(signature, str)
            or not SIGNATURE.fullmatch(signature)
        ):
            raise ValueCommitError("compute_receipt_invalid", 400)
        _parse_timestamp(receipt["completedAt"])
        receipt_bytes = canonical_json(receipt)
        try:
            recovered = Account.recover_message(
                encode_defunct(primitive=receipt_bytes), signature=signature
            )
        except Exception as exc:
            raise ValueCommitError("compute_receipt_signature_invalid", 401) from exc
        if recovered.lower() != self.expected_node_signer:
            raise ValueCommitError("compute_receipt_signature_invalid", 401)
        return deepcopy(receipt), hashlib.sha256(receipt_bytes).hexdigest()

    def _manifest(self, job_id_hash: str) -> tuple[str, Dict[str, Any]]:
        doc_id = self.manifest_id(job_id_hash)
        exists, manifest = self.rewards_dao.get_if_exists(doc_id)
        if not exists:
            raise ValueCommitError("contribution_manifest_not_found", 404)
        stored = _stored_document(manifest)
        if (
            set(stored)
            != {
                "document_type",
                "job_id_hash",
                "release_id",
                "release_id_hash",
                "input_sha256",
                "schema",
                "policy",
                "value_policy",
                "amount",
                "algorithm_image_digest",
                "contributors",
                "status",
            }
            and stored.get("status") == "pending"
        ):
            raise ValueCommitError("value_state_invalid", 503)
        required = {
            "document_type": DOCUMENT_TYPE_MANIFEST,
            "job_id_hash": job_id_hash,
            "schema": INPUT_SCHEMA,
            "policy": INPUT_POLICY,
            "value_policy": VALUE_POLICY,
            "amount": self.amount,
            "algorithm_image_digest": self.approved_algorithm_digest,
        }
        if (
            any(stored.get(key) != value for key, value in required.items())
            or not HEX_64.fullmatch(stored.get("release_id", ""))
            or stored.get("release_id_hash")
            != hashlib.sha256(stored["release_id"].encode("utf-8")).hexdigest()
            or not HEX_64.fullmatch(stored.get("input_sha256", ""))
            or _normalize_contributors(stored.get("contributors", []))
            != stored.get("contributors")
            or stored.get("status") not in {"pending", "committed"}
        ):
            raise ValueCommitError("value_state_invalid", 503)
        return doc_id, manifest

    def _recheck_contributors(self, manifest: Dict[str, Any]) -> None:
        try:
            active_members = CohortReleaseService(
                self.release_dao,
                self.users_dao,
                self.consent_version,
            ).active_member_ids(manifest["release_id"])
        except (KeyError, CohortReleaseError) as exc:
            raise ValueCommitError("contribution_no_longer_eligible", 409) from exc

        for contributor in manifest.get("contributors", []):
            internal_id = contributor["internal_user_id"]
            if internal_id not in active_members:
                raise ValueCommitError("contribution_no_longer_eligible", 409)
            try:
                user = self.users_dao.get_doc_by_id(internal_id)
            except Exception as exc:
                raise ValueCommitError(
                    "contribution_no_longer_eligible", 409
                ) from exc
            if (
                not has_brainstem_data_consent(user)
                or str(user.get("public_address", "")).lower()
                != contributor["public_address"].lower()
            ):
                raise ValueCommitError("contribution_no_longer_eligible", 409)
            for expected_record in contributor["records"]:
                try:
                    record = self.metadata_dao.get_doc_by_id(expected_record["id"])
                except Exception as exc:
                    raise ValueCommitError(
                        "contribution_no_longer_eligible", 409
                    ) from exc
                if (
                    record.get("file_type") != "record"
                    or str(record.get("created_by", "")).lower()
                    != contributor["record_owner"].lower()
                    or record.get("content_hash")
                    != expected_record["content_sha256"]
                ):
                    raise ValueCommitError("contribution_no_longer_eligible", 409)

    @staticmethod
    def _entitlement_id(manifest: Dict[str, Any], internal_user_id: str) -> str:
        digest = hashlib.sha256(
            (
                f"{VALUE_POLICY}\0{manifest['release_id']}\0{internal_user_id}"
            ).encode("utf-8")
        ).hexdigest()
        return f"brainstem-value:{digest}"

    def _sign_commitment(self, commitment: Dict[str, Any]) -> str:
        signed = self.signing_account.sign_message(
            encode_defunct(primitive=canonical_json(commitment))
        )
        signature = signed.signature.hex()
        return signature if signature.startswith("0x") else f"0x{signature}"

    def commit(self, receipt: Any, signature: Any) -> Dict[str, Any]:
        receipt, receipt_sha256 = self._validate_receipt(receipt, signature)
        manifest_id, manifest = self._manifest(receipt["jobIdHash"])
        if (
            manifest.get("input_sha256") != receipt["inputSha256"]
            or manifest.get("algorithm_image_digest")
            != receipt["algorithmImageDigest"]
        ):
            raise ValueCommitError("compute_receipt_mismatch", 409)

        commit_id = f"brainstem-value-commit:{receipt_sha256}"
        created_at = receipt["completedAt"]
        entitlements = []
        entitlement_ids = []
        for contributor in manifest["contributors"]:
            entitlement_id = self._entitlement_id(
                manifest, contributor["internal_user_id"]
            )
            entitlement = {
                "document_type": DOCUMENT_TYPE_ENTITLEMENT,
                "public_address": contributor["public_address"],
                "created_at": created_at,
                "value_policy": VALUE_POLICY,
                "release_id_hash": manifest["release_id_hash"],
                "compute_receipt_sha256": receipt_sha256,
                "commit_id": commit_id,
                "status": RewardStatus.CREATED,
                "source": Source.brainstem,
                "amount": manifest["amount"],
            }
            entitlements.append((entitlement_id, entitlement))
            entitlement_ids.append(entitlement_id)

        entitlement_ids.sort()
        commitment = {
            "schema": COMMITMENT_SCHEMA,
            "computeReceiptSha256": receipt_sha256,
            "valuePolicy": VALUE_POLICY,
            "participantCount": (
                None
                if receipt["resultStatus"] == "insufficient_data"
                else len(entitlement_ids)
            ),
            "amountPerParticipant": manifest["amount"],
            "entitlementSetSha256": hashlib.sha256(
                canonical_json(entitlement_ids)
            ).hexdigest(),
            "committedAt": created_at,
        }
        commitment["signature"] = self._sign_commitment(commitment)
        commit_document = {
            "document_type": DOCUMENT_TYPE_COMMIT,
            "manifest_id": manifest_id,
            "compute_receipt_sha256": receipt_sha256,
            "entitlement_ids": entitlement_ids,
            "status": "committed",
            "commitment": commitment,
        }

        def mark_committed(current):
            if current.get("status") == "committed":
                if current.get("compute_receipt_sha256") != receipt_sha256:
                    raise ValueCommitError("value_state_conflict", 409)
                return None
            if current.get("status") != "pending":
                raise ValueCommitError("value_state_invalid", 503)
            current["status"] = "committed"
            current["compute_receipt_sha256"] = receipt_sha256
            current["result_sha256"] = receipt["resultSha256"]
            current["commit_id"] = commit_id
            current["committed_at"] = created_at
            return current

        if manifest.get("status") == "committed":
            if (
                manifest.get("compute_receipt_sha256") != receipt_sha256
                or manifest.get("commit_id") != commit_id
            ):
                raise ValueCommitError("value_state_conflict", 409)
            exists, current_commit = self.rewards_dao.get_if_exists(commit_id)
            if (
                not exists
                or _stored_document(current_commit) != commit_document
            ):
                raise ValueCommitError("value_state_invalid", 503)
            return deepcopy(commitment)
        if manifest.get("status") != "pending":
            raise ValueCommitError("value_state_invalid", 503)

        exists, _current_commit = self.rewards_dao.get_if_exists(commit_id)
        existing_entitlements = []
        reused_entitlements = set()
        entitlement_policy_fields = {
            "document_type",
            "public_address",
            "value_policy",
            "release_id_hash",
            "source",
            "amount",
        }
        for entitlement_id, entitlement in entitlements:
            entitlement_exists, current = self.rewards_dao.get_if_exists(
                entitlement_id
            )
            if entitlement_exists:
                if _stored_document(current) == entitlement:
                    existing_entitlements.append(entitlement_id)
                elif (
                    {
                        key: current.get(key)
                        for key in entitlement_policy_fields
                    }
                    == {
                        key: entitlement.get(key)
                        for key in entitlement_policy_fields
                    }
                    and entitlement_id
                    in self.rewards_dao.committed_brainstem_value_entitlement_ids(
                        [current]
                    )
                ):
                    reused_entitlements.add(entitlement_id)
                else:
                    raise ValueCommitError("value_state_invalid", 503)

        if exists or existing_entitlements:
            for entitlement_id, entitlement in entitlements:
                if entitlement_id not in reused_entitlements:
                    _save_exactly_once(
                        self.rewards_dao, entitlement_id, entitlement
                    )
            _save_exactly_once(self.rewards_dao, commit_id, commit_document)
            self.rewards_dao.mutate_doc(manifest_id, mark_committed)
            return deepcopy(commitment)

        self._recheck_contributors(manifest)
        for entitlement_id, entitlement in entitlements:
            if entitlement_id not in reused_entitlements:
                _save_exactly_once(self.rewards_dao, entitlement_id, entitlement)
        _save_exactly_once(self.rewards_dao, commit_id, commit_document)
        self.rewards_dao.mutate_doc(manifest_id, mark_committed)
        return deepcopy(commitment)
