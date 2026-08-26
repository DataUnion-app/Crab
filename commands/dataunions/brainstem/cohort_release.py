from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import re
import secrets
from typing import Any, Dict, Set

from commands.dataunions.brainstem.consent import has_brainstem_data_consent
from commands.dataunions.brainstem.limits import MINIMUM_DISCLOSURE_PARTICIPANTS
from commands.dataunions.brainstem.record_contract import CONTRACT_VERSION


DOCUMENT_TYPE = "brainstem_c2d_cohort_release"
DATA_UNION = "brainstem"
PURPOSE = "brainstem.resting-rr/v1"
RELEASE_ID_PATTERN = re.compile(r"^[0-9a-f]{64}$")
HEX_64_PATTERN = re.compile(r"^[0-9a-f]{64}$")
CONSENT_VERSION_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$")
REFERENCE_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{7,127}$")
MAX_ROSTER_SIZE = 1_000
MAX_RELEASE_LIFETIME = timedelta(days=14)
MAX_REFRESH_RECORDS = 20_000


class CohortReleaseError(RuntimeError):
    def __init__(self, code: str, status_code: int = 422):
        super().__init__(code)
        self.code = code
        self.status_code = status_code


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _timestamp(value: Any, field: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise CohortReleaseError(f"{field}_invalid", 400)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise CohortReleaseError(f"{field}_invalid", 400) from exc
    if parsed.tzinfo is None:
        raise CohortReleaseError(f"{field}_invalid", 400)
    return parsed.astimezone(timezone.utc)


def _formatted(value: datetime) -> str:
    return (
        value.astimezone(timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


def _reference_hash(value: Any, field: str) -> str:
    if not isinstance(value, str) or not REFERENCE_PATTERN.fullmatch(value):
        raise CohortReleaseError(f"{field}_invalid", 400)
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _roster(value: Any) -> list[str]:
    if not isinstance(value, list) or not 1 <= len(value) <= MAX_ROSTER_SIZE:
        raise CohortReleaseError("release_roster_invalid", 400)
    if any(
        not isinstance(user_id, str)
        or not 1 <= len(user_id) <= 128
        or any(character in user_id for character in "\r\n\0")
        for user_id in value
    ):
        raise CohortReleaseError("release_roster_invalid", 400)
    if len(set(value)) != len(value):
        raise CohortReleaseError("release_roster_invalid", 400)
    return sorted(value)


class CohortReleaseService:
    def __init__(
        self,
        release_dao,
        users_dao,
        consent_version: str,
        now=_utc_now,
        metadata_dao=None,
        refresh_min_contributors: int = 20,
        refresh_min_age: timedelta = timedelta(days=7),
        minimum_release_participants: int = MINIMUM_DISCLOSURE_PARTICIPANTS,
        purpose: str = PURPOSE,
        consent_checker=has_brainstem_data_consent,
        record_type: str = "rest",
    ):
        if (
            not isinstance(consent_version, str)
            or not CONSENT_VERSION_PATTERN.fullmatch(consent_version)
            or not isinstance(refresh_min_contributors, int)
            or not (2 <= refresh_min_contributors <= MAX_ROSTER_SIZE)
            or not isinstance(refresh_min_age, timedelta)
            or not (timedelta(days=1) <= refresh_min_age <= MAX_RELEASE_LIFETIME)
            or not isinstance(minimum_release_participants, int)
            or not 1 <= minimum_release_participants <= MAX_ROSTER_SIZE
            or not isinstance(purpose, str)
            or not REFERENCE_PATTERN.fullmatch(purpose)
            or not callable(consent_checker)
            or record_type not in {"rest", "sleep"}
        ):
            raise CohortReleaseError("release_configuration_invalid", 503)
        self.release_dao = release_dao
        self.users_dao = users_dao
        self.consent_version = consent_version
        self.now = now
        self.metadata_dao = metadata_dao
        self.refresh_min_contributors = refresh_min_contributors
        self.refresh_min_age = refresh_min_age
        self.minimum_release_participants = minimum_release_participants
        self.purpose = purpose
        self.consent_checker = consent_checker
        self.record_type = record_type

    def _member_revisions(self, roster: list[str]) -> Dict[str, str]:
        if self.metadata_dao is None:
            raise CohortReleaseError("refresh_unavailable", 503)
        address_to_user = {}
        for user_id in roster:
            try:
                user = self.users_dao.get_doc_by_id(user_id)
            except Exception as exc:
                raise CohortReleaseError("release_member_ineligible") from exc
            address = user.get("public_address")
            if (
                not self.consent_checker(user)
                or not isinstance(address, str)
                or not address
                or address in address_to_user
            ):
                raise CohortReleaseError("release_member_ineligible")
            address_to_user[address] = user_id

        records = {user_id: [] for user_id in roster}
        query = {
            "selector": {
                "file_type": "record",
                "record_contract_version": CONTRACT_VERSION,
                "record_type": self.record_type,
                "recognized_payloads": {"$elemMatch": {"$eq": "hbr_rr"}},
            },
            "fields": ["_id", "created_by", "content_hash"],
        }
        inspected = 0
        for document in self.metadata_dao.iter_query(query, batch_size=500):
            inspected += 1
            if inspected > MAX_REFRESH_RECORDS:
                raise CohortReleaseError("refresh_source_limit", 503)
            user_id = address_to_user.get(document.get("created_by"))
            if user_id is None:
                continue
            record_id = document.get("_id")
            content_hash = document.get("content_hash")
            if (
                not isinstance(record_id, str)
                or not record_id
                or not isinstance(content_hash, str)
                or not HEX_64_PATTERN.fullmatch(content_hash)
            ):
                raise CohortReleaseError("refresh_source_invalid", 503)
            records[user_id].append((record_id, content_hash))

        return {
            user_id: hashlib.sha256(
                "\n".join(
                    f"{record_id}\0{content_hash}"
                    for record_id, content_hash in sorted(records[user_id])
                ).encode("utf-8")
            ).hexdigest()
            for user_id in roster
        }

    def create(
        self,
        roster_user_ids: Any,
        expires_at: Any,
        *,
        release_id: str | None = None,
        member_revisions: Dict[str, str] | None = None,
        parent_release_id: str | None = None,
    ) -> Dict[str, Any]:
        roster = _roster(roster_user_ids)
        if len(roster) < self.minimum_release_participants:
            raise CohortReleaseError("release_privacy_floor", 409)
        now = self.now()
        expiry = _timestamp(expires_at, "release_expiry")
        if expiry <= now or expiry > now + MAX_RELEASE_LIFETIME:
            raise CohortReleaseError("release_expired", 400)
        release_id = release_id or secrets.token_hex(32)
        if not RELEASE_ID_PATTERN.fullmatch(release_id):
            raise CohortReleaseError("invalid_release_id", 400)
        if member_revisions is None and self.metadata_dao is not None:
            member_revisions = self._member_revisions(roster)
        document = {
            "document_type": DOCUMENT_TYPE,
            "release_id": release_id,
            "data_union": DATA_UNION,
            "purpose": self.purpose,
            "consent_version": self.consent_version,
            "status": "draft",
            "roster_user_ids": roster,
            "created_at": _formatted(now),
            "expires_at": _formatted(expiry),
        }
        if member_revisions is not None:
            if set(member_revisions) != set(roster) or any(
                not isinstance(value, str) or not HEX_64_PATTERN.fullmatch(value)
                for value in member_revisions.values()
            ):
                raise CohortReleaseError("refresh_source_invalid", 503)
            document["source_revision"] = secrets.token_hex(32)
            document["source_member_revisions"] = {
                user_id: member_revisions[user_id] for user_id in roster
            }
        if parent_release_id is not None:
            if not RELEASE_ID_PATTERN.fullmatch(parent_release_id):
                raise CohortReleaseError("invalid_release_id", 400)
            document["parent_release_id"] = parent_release_id
        self.release_dao.save(f"brainstem-c2d-release:{release_id}", document)
        return deepcopy(document)

    def _document(self, release_id: str) -> Dict[str, Any]:
        if not isinstance(release_id, str) or not RELEASE_ID_PATTERN.fullmatch(
            release_id
        ):
            raise CohortReleaseError("invalid_release_id", 400)
        try:
            document = self.release_dao.get_doc_by_id(
                f"brainstem-c2d-release:{release_id}"
            )
        except Exception as exc:
            raise CohortReleaseError("release_not_found", 404) from exc
        if not isinstance(document, dict):
            raise CohortReleaseError("release_invalid")
        return document

    def _validate_contract(self, document: Dict[str, Any], release_id: str) -> None:
        if (
            document.get("document_type") != DOCUMENT_TYPE
            or document.get("release_id") != release_id
            or document.get("data_union") != DATA_UNION
            or document.get("purpose") != self.purpose
            or document.get("consent_version") != self.consent_version
        ):
            raise CohortReleaseError("release_contract_mismatch")
        _roster(document.get("roster_user_ids"))
        _timestamp(document.get("created_at"), "release_created_at")
        _timestamp(document.get("expires_at"), "release_expiry")
        source_revision = document.get("source_revision")
        source_members = document.get("source_member_revisions")
        if source_revision is not None or source_members is not None:
            if (
                not isinstance(source_revision, str)
                or not HEX_64_PATTERN.fullmatch(source_revision)
                or not isinstance(source_members, dict)
                or set(source_members) != set(document["roster_user_ids"])
                or any(
                    not isinstance(value, str) or not HEX_64_PATTERN.fullmatch(value)
                    for value in source_members.values()
                )
            ):
                raise CohortReleaseError("release_contract_mismatch")

    def activate(self, release_id: str, approval_reference: Any) -> Dict[str, Any]:
        approval_hash = _reference_hash(approval_reference, "approval_reference")
        now = self.now()

        def activate_document(document):
            self._validate_contract(document, release_id)
            if document.get("status") != "draft":
                raise CohortReleaseError("release_not_draft")
            if _timestamp(document["expires_at"], "release_expiry") <= now:
                raise CohortReleaseError("release_expired")
            for user_id in document["roster_user_ids"]:
                try:
                    user = self.users_dao.get_doc_by_id(user_id)
                except Exception as exc:
                    raise CohortReleaseError("release_member_ineligible") from exc
                if not self.consent_checker(user):
                    raise CohortReleaseError("release_member_ineligible")
            document["status"] = "active"
            document["activated_at"] = _formatted(now)
            document["approval_reference_hash"] = approval_hash
            return document

        try:
            self.release_dao.mutate_doc(
                f"brainstem-c2d-release:{release_id}", activate_document
            )
        except CohortReleaseError:
            raise
        except Exception as exc:
            raise CohortReleaseError("release_activation_failed", 503) from exc
        return self._document(release_id)

    def revoke(self, release_id: str, reason_reference: Any) -> Dict[str, Any]:
        reason_hash = _reference_hash(reason_reference, "reason_reference")
        now = self.now()

        def revoke_document(document):
            self._validate_contract(document, release_id)
            if document.get("status") not in {"draft", "active"}:
                raise CohortReleaseError("release_not_revocable")
            document["status"] = "revoked"
            document["revoked_at"] = _formatted(now)
            document["reason_reference_hash"] = reason_hash
            return document

        try:
            self.release_dao.mutate_doc(
                f"brainstem-c2d-release:{release_id}", revoke_document
            )
        except CohortReleaseError:
            raise
        except Exception as exc:
            raise CohortReleaseError("release_revocation_failed", 503) from exc
        return self._document(release_id)

    def active_member_ids(self, release_id: str) -> Set[str]:
        document = self._document(release_id)
        self._validate_contract(document, release_id)
        if document.get("status") != "active":
            raise CohortReleaseError("release_not_active")
        if _timestamp(document["expires_at"], "release_expiry") <= self.now():
            raise CohortReleaseError("release_expired")
        if not isinstance(document.get("activated_at"), str):
            raise CohortReleaseError("release_invalid")
        _timestamp(document["activated_at"], "release_activated_at")
        return set(document["roster_user_ids"])

    def _refresh_projection(
        self, state: str, revision: str, evaluated_at: datetime
    ) -> Dict[str, str]:
        return {
            "state": state,
            "revision": revision,
            "evaluatedAt": _formatted(
                evaluated_at.replace(hour=0, minute=0, second=0, microsecond=0)
            ),
        }

    def refresh_status(self, release_id: str) -> Dict[str, str]:
        document = self._document(release_id)
        self._validate_contract(document, release_id)
        if (
            document.get("status") != "active"
            or _timestamp(document["expires_at"], "release_expiry") <= self.now()
        ):
            return self._refresh_projection(
                "unavailable",
                release_id,
                _timestamp(document["created_at"], "release_created_at"),
            )
        state = document.get("refresh_state")
        revision = document.get("refresh_revision")
        evaluated_at = document.get("refresh_evaluated_at")
        if (
            state not in {"current", "refresh_available", "unavailable"}
            or not isinstance(revision, str)
            or not RELEASE_ID_PATTERN.fullmatch(revision)
            or not isinstance(evaluated_at, str)
        ):
            return self._refresh_projection(
                "unavailable",
                release_id,
                _timestamp(document["created_at"], "release_created_at"),
            )
        return self._refresh_projection(
            state, revision, _timestamp(evaluated_at, "refresh_evaluated_at")
        )

    def _record_refresh(
        self, release_id: str, state: str, revision: str, evaluated_at: datetime
    ) -> Dict[str, str]:
        def update(document):
            self._validate_contract(document, release_id)
            document["refresh_state"] = state
            document["refresh_revision"] = revision
            document["refresh_evaluated_at"] = _formatted(evaluated_at)
            return document

        try:
            self.release_dao.mutate_doc(f"brainstem-c2d-release:{release_id}", update)
        except CohortReleaseError:
            raise
        except Exception as exc:
            raise CohortReleaseError("refresh_update_failed", 503) from exc
        return self.refresh_status(release_id)

    def evaluate_refresh(self, release_id: str) -> Dict[str, str]:
        now = self.now()
        document = self._document(release_id)
        self._validate_contract(document, release_id)
        if (
            document.get("status") != "active"
            or _timestamp(document["expires_at"], "release_expiry") <= now
            or not isinstance(document.get("activated_at"), str)
        ):
            return self._record_refresh(release_id, "unavailable", release_id, now)
        baseline = document.get("source_member_revisions")
        if not isinstance(baseline, dict):
            return self._record_refresh(release_id, "unavailable", release_id, now)
        try:
            current = self._member_revisions(document["roster_user_ids"])
        except CohortReleaseError:
            return self._record_refresh(release_id, "unavailable", release_id, now)
        existing_draft = document.get("refresh_draft_id")
        if (
            document.get("refresh_state") == "refresh_available"
            and isinstance(existing_draft, str)
            and RELEASE_ID_PATTERN.fullmatch(existing_draft)
        ):
            return self._record_refresh(
                release_id, "refresh_available", existing_draft, now
            )
        changed = sum(
            current.get(user_id) != baseline.get(user_id)
            for user_id in document["roster_user_ids"]
        )
        activated_at = _timestamp(document["activated_at"], "release_activated_at")
        if (
            changed < self.refresh_min_contributors
            or now - activated_at < self.refresh_min_age
        ):
            return self._record_refresh(release_id, "current", release_id, now)

        source_digest = hashlib.sha256(
            "\n".join(
                f"{user_id}\0{current[user_id]}" for user_id in sorted(current)
            ).encode("utf-8")
        ).digest()
        draft_id = hmac.new(
            bytes.fromhex(release_id), source_digest, hashlib.sha256
        ).hexdigest()
        try:
            self.create(
                document["roster_user_ids"],
                _formatted(now + MAX_RELEASE_LIFETIME),
                release_id=draft_id,
                member_revisions=current,
                parent_release_id=release_id,
            )
        except Exception as create_error:
            try:
                draft = self._document(draft_id)
                self._validate_contract(draft, draft_id)
                if (
                    draft.get("status") != "draft"
                    or draft.get("parent_release_id") != release_id
                    or draft.get("roster_user_ids") != document["roster_user_ids"]
                    or draft.get("source_member_revisions") != current
                ):
                    raise CohortReleaseError("refresh_draft_invalid", 503)
            except CohortReleaseError as exc:
                raise CohortReleaseError("refresh_draft_failed", 503) from (
                    create_error if exc.code == "release_not_found" else exc
                )
            except Exception as exc:
                raise CohortReleaseError("refresh_draft_failed", 503) from exc

        def publish_readiness(current_document):
            self._validate_contract(current_document, release_id)
            current_document["refresh_draft_id"] = draft_id
            current_document["refresh_state"] = "refresh_available"
            current_document["refresh_revision"] = draft_id
            current_document["refresh_evaluated_at"] = _formatted(now)
            return current_document

        try:
            self.release_dao.mutate_doc(
                f"brainstem-c2d-release:{release_id}", publish_readiness
            )
        except Exception as exc:
            raise CohortReleaseError("refresh_update_failed", 503) from exc
        return self.refresh_status(release_id)
