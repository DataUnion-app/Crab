from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import re
from typing import Any, Dict


DOCUMENT_TYPE = "brainstem_c2d_cohort_reference_registry"
MAX_REVISIONS = 64
HEX_64 = re.compile(r"^[0-9a-f]{64}$")
IMAGE_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
VERSION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
SUPPORTED_ANALYSES = {
    "brainstem.resting-hrv-methods/v1",
    "brainstem.resting-rr-sample-entropy/v1",
}


class CohortReferenceError(RuntimeError):
    def __init__(self, code: str, status_code: int = 422):
        super().__init__(code)
        self.code = code
        self.status_code = status_code


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _time(value: datetime) -> str:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise CohortReferenceError("reference_time_invalid")
    return (
        value.astimezone(timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


def _day(value: str) -> str:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return _time(parsed.replace(hour=0, minute=0, second=0, microsecond=0))


def _hash_reference(value: Any, field: str) -> str:
    if (
        not isinstance(value, str)
        or not 8 <= len(value) <= 160
        or any(character in value for character in "\r\n\0")
    ):
        raise CohortReferenceError(f"{field}_invalid", 400)
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _registry_id(analysis_id: str) -> str:
    return "brainstem-cohort-reference:{}".format(
        hashlib.sha256(analysis_id.encode("utf-8")).hexdigest()
    )


def _revision(
    *,
    analysis_id: str,
    reference_sha256: str,
    artifact_sha256: str,
    version: str,
    source_release_id: str,
    algorithm_image_digest: str,
    approved_manifest_sha256: str,
    supersedes: str | None,
    drafted_at: str,
) -> Dict[str, Any]:
    if (
        analysis_id not in SUPPORTED_ANALYSES
        or not isinstance(reference_sha256, str)
        or not HEX_64.fullmatch(reference_sha256)
        or not isinstance(artifact_sha256, str)
        or not HEX_64.fullmatch(artifact_sha256)
        or not isinstance(version, str)
        or not VERSION.fullmatch(version)
        or not isinstance(source_release_id, str)
        or not HEX_64.fullmatch(source_release_id)
        or not isinstance(algorithm_image_digest, str)
        or not IMAGE_DIGEST.fullmatch(algorithm_image_digest)
        or not isinstance(approved_manifest_sha256, str)
        or not HEX_64.fullmatch(approved_manifest_sha256)
        or (
            supersedes is not None
            and (
                not isinstance(supersedes, str)
                or not HEX_64.fullmatch(supersedes)
                or supersedes == reference_sha256
            )
        )
    ):
        raise CohortReferenceError("reference_contract_invalid", 400)
    return {
        "reference_id": reference_sha256,
        "version": version,
        "artifact_sha256": artifact_sha256,
        "source_release_id": source_release_id,
        "algorithm_image_digest": algorithm_image_digest,
        "approved_manifest_sha256": approved_manifest_sha256,
        "supersedes": supersedes,
        "state": "draft",
        "drafted_at": drafted_at,
        "activated_at": None,
        "ended_at": None,
        "reason_reference_hash": None,
    }


def _validate_registry(value: Any, analysis_id: str) -> Dict[str, Any]:
    if (
        not isinstance(value, dict)
        or value.get("document_type") != DOCUMENT_TYPE
        or value.get("analysis_id") != analysis_id
        or value.get("current_reference_id") is not None
        and (
            not isinstance(value.get("current_reference_id"), str)
            or not HEX_64.fullmatch(value["current_reference_id"])
        )
        or not isinstance(value.get("revisions"), list)
        or not value["revisions"]
        or len(value["revisions"]) > MAX_REVISIONS
    ):
        raise CohortReferenceError("reference_registry_invalid")
    seen = set()
    active = []
    for item in value["revisions"]:
        if not isinstance(item, dict) or set(item) != {
            "reference_id",
            "version",
            "artifact_sha256",
            "source_release_id",
            "algorithm_image_digest",
            "approved_manifest_sha256",
            "supersedes",
            "state",
            "drafted_at",
            "activated_at",
            "ended_at",
            "reason_reference_hash",
        }:
            raise CohortReferenceError("reference_registry_invalid")
        validated = _revision(
            analysis_id=analysis_id,
            reference_sha256=item["reference_id"],
            artifact_sha256=item["artifact_sha256"],
            version=item["version"],
            source_release_id=item["source_release_id"],
            algorithm_image_digest=item["algorithm_image_digest"],
            approved_manifest_sha256=item["approved_manifest_sha256"],
            supersedes=item["supersedes"],
            drafted_at=item["drafted_at"],
        )
        if (
            item["reference_id"] in seen
            or item["state"]
            not in {"draft", "active", "superseded", "withdrawn", "deleted"}
            or (
                item["state"] == "draft"
                and (
                    item["activated_at"] is not None
                    or item["ended_at"] is not None
                    or item["reason_reference_hash"] is not None
                )
            )
            or (
                item["state"] == "active"
                and (
                    not isinstance(item["activated_at"], str)
                    or item["ended_at"] is not None
                )
            )
            or (
                item["state"] in {"superseded", "withdrawn", "deleted"}
                and (
                    not isinstance(item["activated_at"], str)
                    or not isinstance(item["ended_at"], str)
                )
            )
            or (
                item["reason_reference_hash"] is not None
                and (
                    not isinstance(item["reason_reference_hash"], str)
                    or not HEX_64.fullmatch(item["reason_reference_hash"])
                )
            )
        ):
            raise CohortReferenceError("reference_registry_invalid")
        immutable = {
            "reference_id",
            "version",
            "artifact_sha256",
            "source_release_id",
            "algorithm_image_digest",
            "approved_manifest_sha256",
            "supersedes",
            "drafted_at",
        }
        if any(item[key] != validated[key] for key in immutable):
            raise CohortReferenceError("reference_registry_invalid")
        seen.add(item["reference_id"])
        if item["state"] == "active":
            active.append(item["reference_id"])
    if (
        len(active) > 1
        or active
        and value["current_reference_id"] != active[0]
        or not active
        and value["current_reference_id"] is not None
    ):
        raise CohortReferenceError("reference_registry_invalid")
    return value


class CohortReferenceService:
    """Finite reference lifecycle for the two reviewed E2 analyses."""

    def __init__(self, dao, release_service, now=_now):
        self.dao = dao
        self.release_service = release_service
        self.now = now

    def _get(self, analysis_id: str) -> Dict[str, Any]:
        if analysis_id not in SUPPORTED_ANALYSES:
            raise CohortReferenceError("reference_analysis_invalid", 404)
        try:
            document = self.dao.get_doc_by_id(_registry_id(analysis_id))
        except Exception as error:
            raise CohortReferenceError("reference_not_found", 404) from error
        return _validate_registry(document, analysis_id)

    def draft(
        self,
        *,
        analysis_id: str,
        reference_sha256: str,
        artifact_sha256: str,
        version: str,
        source_release_id: str,
        algorithm_image_digest: str,
        approved_manifest_sha256: str,
        supersedes: str | None = None,
    ) -> Dict[str, Any]:
        drafted_at = _time(self.now())
        revision = _revision(
            analysis_id=analysis_id,
            reference_sha256=reference_sha256,
            artifact_sha256=artifact_sha256,
            version=version,
            source_release_id=source_release_id,
            algorithm_image_digest=algorithm_image_digest,
            approved_manifest_sha256=approved_manifest_sha256,
            supersedes=supersedes,
            drafted_at=drafted_at,
        )
        self.release_service.active_member_ids(source_release_id)
        if supersedes is not None:
            try:
                predecessor = self.reference(analysis_id, supersedes)
            except CohortReferenceError as error:
                raise CohortReferenceError(
                    "reference_predecessor_invalid"
                ) from error
            if predecessor["state"] not in {"active", "superseded"}:
                raise CohortReferenceError("reference_predecessor_invalid")
        doc_id = _registry_id(analysis_id)

        def add(document):
            _validate_registry(document, analysis_id)
            existing = next(
                (
                    item
                    for item in document["revisions"]
                    if item["reference_id"] == reference_sha256
                ),
                None,
            )
            if existing is not None:
                contract = {
                    "reference_id",
                    "version",
                    "artifact_sha256",
                    "source_release_id",
                    "algorithm_image_digest",
                    "approved_manifest_sha256",
                    "supersedes",
                }
                if any(existing[key] != revision[key] for key in contract):
                    raise CohortReferenceError("reference_conflict")
                return document
            if len(document["revisions"]) >= MAX_REVISIONS:
                raise CohortReferenceError("reference_limit_exceeded", 413)
            if (
                document["current_reference_id"] is not None
                and supersedes is None
            ):
                raise CohortReferenceError("reference_predecessor_invalid")
            if supersedes is not None and not any(
                item["reference_id"] == supersedes
                and item["state"] in {"active", "superseded"}
                for item in document["revisions"]
            ):
                raise CohortReferenceError("reference_predecessor_invalid")
            document["revisions"].append(revision)
            return document

        try:
            self.dao.mutate_doc(doc_id, add)
        except CohortReferenceError:
            raise
        except Exception:
            document = {
                "document_type": DOCUMENT_TYPE,
                "analysis_id": analysis_id,
                "current_reference_id": None,
                "revisions": [revision],
            }
            try:
                self.dao.save(doc_id, document)
            except Exception:
                try:
                    self.dao.mutate_doc(doc_id, add)
                except CohortReferenceError:
                    raise
                except Exception as error:
                    raise CohortReferenceError(
                        "reference_draft_failed", 503
                    ) from error
        return self.reference(analysis_id, reference_sha256)

    def reference(self, analysis_id: str, reference_id: str) -> Dict[str, Any]:
        if not isinstance(reference_id, str) or not HEX_64.fullmatch(reference_id):
            raise CohortReferenceError("reference_id_invalid", 400)
        document = self._get(analysis_id)
        for item in document["revisions"]:
            if item["reference_id"] == reference_id:
                return deepcopy(item)
        raise CohortReferenceError("reference_not_found", 404)

    def activate(
        self, analysis_id: str, reference_id: str, review_reference: Any
    ) -> Dict[str, Any]:
        review_hash = _hash_reference(review_reference, "review_reference")
        now = _time(self.now())

        def update(document):
            _validate_registry(document, analysis_id)
            target = next(
                (
                    item
                    for item in document["revisions"]
                    if item["reference_id"] == reference_id
                ),
                None,
            )
            if target is None:
                raise CohortReferenceError("reference_not_found", 404)
            if target["state"] != "draft":
                raise CohortReferenceError("reference_not_draft")
            self.release_service.active_member_ids(target["source_release_id"])
            current_id = document["current_reference_id"]
            if current_id is not None:
                if target["supersedes"] != current_id:
                    raise CohortReferenceError("reference_predecessor_invalid")
                current = next(
                    item
                    for item in document["revisions"]
                    if item["reference_id"] == current_id
                )
                current["state"] = "superseded"
                current["ended_at"] = now
            elif target["supersedes"] is not None:
                raise CohortReferenceError("reference_predecessor_invalid")
            target["state"] = "active"
            target["activated_at"] = now
            target["reason_reference_hash"] = review_hash
            document["current_reference_id"] = reference_id
            return document

        try:
            self.dao.mutate_doc(_registry_id(analysis_id), update)
        except CohortReferenceError:
            raise
        except Exception as error:
            raise CohortReferenceError("reference_activation_failed", 503) from error
        return self.reference(analysis_id, reference_id)

    def withdraw(
        self, analysis_id: str, reference_id: str, reason_reference: Any
    ) -> Dict[str, Any]:
        reason_hash = _hash_reference(reason_reference, "reason_reference")
        now = _time(self.now())

        def update(document):
            _validate_registry(document, analysis_id)
            target = next(
                (
                    item
                    for item in document["revisions"]
                    if item["reference_id"] == reference_id
                ),
                None,
            )
            if target is None:
                raise CohortReferenceError("reference_not_found", 404)
            if target["state"] not in {"active", "superseded"}:
                raise CohortReferenceError("reference_not_withdrawable")
            target["state"] = "withdrawn"
            target["ended_at"] = target["ended_at"] or now
            target["reason_reference_hash"] = reason_hash
            if document["current_reference_id"] == reference_id:
                document["current_reference_id"] = None
            return document

        try:
            self.dao.mutate_doc(_registry_id(analysis_id), update)
        except CohortReferenceError:
            raise
        except Exception as error:
            raise CohortReferenceError("reference_withdrawal_failed", 503) from error
        return self.reference(analysis_id, reference_id)

    def delete(
        self, analysis_id: str, reference_id: str, reason_reference: Any
    ) -> Dict[str, Any]:
        reason_hash = _hash_reference(reason_reference, "reason_reference")

        def update(document):
            _validate_registry(document, analysis_id)
            target = next(
                (
                    item
                    for item in document["revisions"]
                    if item["reference_id"] == reference_id
                ),
                None,
            )
            if target is None:
                raise CohortReferenceError("reference_not_found", 404)
            if target["state"] != "withdrawn":
                raise CohortReferenceError("reference_not_deletable")
            target["state"] = "deleted"
            target["reason_reference_hash"] = reason_hash
            return document

        try:
            self.dao.mutate_doc(_registry_id(analysis_id), update)
        except CohortReferenceError:
            raise
        except Exception as error:
            raise CohortReferenceError("reference_deletion_failed", 503) from error
        return self.reference(analysis_id, reference_id)

    def is_usable(self, analysis_id: str, reference_id: str) -> bool:
        return self.bound_state(analysis_id, reference_id) == "current"

    def bound_state(
        self,
        analysis_id: str,
        reference_id: str,
        *,
        algorithm_image_digest: str | None = None,
        approved_manifest_sha256: str | None = None,
    ) -> str:
        """Return the only reference states a result consumer may act on."""
        try:
            document = self._get(analysis_id)
            revision = next(
                item
                for item in document["revisions"]
                if item["reference_id"] == reference_id
            )
        except (CohortReferenceError, StopIteration):
            return "unavailable"
        if (
            algorithm_image_digest is not None
            and revision["algorithm_image_digest"] != algorithm_image_digest
        ) or (
            approved_manifest_sha256 is not None
            and revision["approved_manifest_sha256"]
            != approved_manifest_sha256
        ):
            return "unavailable"
        if (
            revision["state"] == "active"
            and document["current_reference_id"] == reference_id
        ):
            try:
                self.release_service.active_member_ids(
                    revision["source_release_id"]
                )
            except Exception:
                return "unavailable"
            return "current"
        if revision["state"] == "superseded":
            return "superseded"
        return "unavailable"

    def public_projection(self, analysis_id: str) -> Dict[str, str]:
        try:
            document = self._get(analysis_id)
        except CohortReferenceError:
            return {
                "state": "unavailable",
                "revision": "0" * 64,
                "evaluatedAt": _day(_time(self.now())),
            }
        current = document["current_reference_id"]
        if current is None:
            revision = document["revisions"][-1]["reference_id"]
            state = "unavailable"
        else:
            current_revision = next(
                item
                for item in document["revisions"]
                if item["reference_id"] == current
            )
            try:
                self.release_service.active_member_ids(
                    current_revision["source_release_id"]
                )
            except Exception:
                return {
                    "state": "unavailable",
                    "revision": current,
                    "evaluatedAt": _day(_time(self.now())),
                }
            successor = next(
                (
                    item["reference_id"]
                    for item in document["revisions"]
                    if item["state"] == "draft" and item["supersedes"] == current
                ),
                None,
            )
            revision = successor or current
            state = "refresh_available" if successor else "current"
        return {
            "state": state,
            "revision": revision,
            "evaluatedAt": _day(_time(self.now())),
        }
