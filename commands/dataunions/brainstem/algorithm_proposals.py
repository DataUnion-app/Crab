import copy
import re
import uuid
from datetime import datetime, timezone
from urllib.parse import urlsplit


INPUT_SCHEMA_VERSION = "brainstem.private-rr-cohort/v1"
RESULT_SCHEMA_VERSION = "brainstem.c2d-result/v1"
SECURITY_SCAN_POLICY = "brainstem.no-high-critical/v1"
MAX_REVISIONS = 20
MAX_EVENTS = 100
VALID_STATES = {
    "submitted",
    "reviewing",
    "changes_requested",
    "rejected",
    "approved",
    "published",
    "whitelisted",
}
ADMIN_TRANSITIONS = {
    "submitted": {"reviewing"},
    "reviewing": {"changes_requested", "rejected", "approved"},
    "approved": {"published"},
    "published": {"whitelisted"},
}

WALLET_PATTERN = re.compile(r"^0x[0-9a-fA-F]{40}$")
PROPOSAL_ID_PATTERN = re.compile(r"^proposal_[0-9a-f]{1,64}$")
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
IMAGE_DIGEST_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
DID_PATTERN = re.compile(r"^did:ope:[0-9a-f]{64}$")
TX_HASH_PATTERN = re.compile(r"^0x[0-9a-fA-F]{64}$")
SOURCE_COMMIT_PATTERN = re.compile(r"^[0-9a-f]{40,64}$")
SERVICE_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
SCANNER_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{1,63}$")
SCANNER_VERSION_PATTERN = re.compile(
    r"^v?[0-9]+\.[0-9]+\.[0-9]+(?:[-+][A-Za-z0-9.-]+)?$"
)
UTC_TIMESTAMP_PATTERN = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,6})?Z$"
)

REVISION_FIELDS = {
    "title",
    "scientific_purpose",
    "source_url",
    "paper_url",
    "input_schema_version",
    "result_schema_version",
}
EVENT_COMMON_FIELDS = {"type", "expected_revision_id", "note"}
EVENT_EVIDENCE_FIELDS = {
    "source_commit",
    "source_sha256",
    "reviewed_image_digest",
    "security_review_ref",
    "security_scan_report_ref",
    "security_scan_report_sha256",
    "security_scan_scanner",
    "security_scan_scanner_version",
    "security_scan_policy",
    "security_scan_completed_at",
    "scientific_review_ref",
    "image_digest",
    "algorithm_did",
    "service_id",
    "chain_id",
    "publication_tx_hash",
    "dataset_did",
    "allowlist_tx_hash",
}


class AlgorithmProposalError(Exception):
    status_code = 400

    def __init__(self, message):
        self.message = message
        super().__init__(message)


class ProposalValidationError(AlgorithmProposalError):
    status_code = 400


class ProposalForbiddenError(AlgorithmProposalError):
    status_code = 403


class ProposalNotFoundError(AlgorithmProposalError):
    status_code = 404


class ProposalConflictError(AlgorithmProposalError):
    status_code = 409


class ProposalPayloadTooLargeError(AlgorithmProposalError):
    status_code = 413


def _utc_now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _new_id(prefix):
    return "{}_{}".format(prefix, uuid.uuid4().hex)


def normalize_wallet(value):
    if not isinstance(value, str) or not WALLET_PATTERN.fullmatch(value):
        raise ProposalValidationError("Invalid wallet identity")
    return value.lower()


def normalize_proposal_id(value):
    if not isinstance(value, str) or not PROPOSAL_ID_PATTERN.fullmatch(value):
        raise ProposalValidationError("Invalid proposal ID")
    return value


def _bounded_text(payload, name, minimum, maximum, multiline=False):
    value = payload.get(name)
    if not isinstance(value, str):
        raise ProposalValidationError("{} must be text".format(name))
    value = value.strip()
    if len(value) < minimum or len(value) > maximum:
        raise ProposalValidationError(
            "{} must contain between {} and {} characters".format(
                name, minimum, maximum
            )
        )
    for character in value:
        if ord(character) < 32 and not (multiline and character in "\n\t"):
            raise ProposalValidationError("{} contains control characters".format(name))
    return value


def _optional_text(payload, name, maximum):
    value = payload.get(name)
    if value is None or value == "":
        return None
    return _bounded_text(payload, name, 1, maximum, multiline=True)


def _https_url(payload, name, required):
    value = payload.get(name)
    if value is None or value == "":
        if required:
            raise ProposalValidationError("{} is required".format(name))
        return None
    value = _bounded_text(payload, name, 1, 2048)
    try:
        parsed = urlsplit(value)
        hostname = parsed.hostname
    except ValueError:
        raise ProposalValidationError("{} must be a public HTTPS URL".format(name))
    if (
        parsed.scheme != "https"
        or not hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
    ):
        raise ProposalValidationError("{} must be a public HTTPS URL".format(name))
    return value


def validate_revision_payload(payload):
    if not isinstance(payload, dict):
        raise ProposalValidationError("A JSON object is required")
    unknown = set(payload) - REVISION_FIELDS
    missing = REVISION_FIELDS - {"paper_url"} - set(payload)
    if unknown or missing:
        raise ProposalValidationError("Invalid proposal fields")

    input_schema = payload.get("input_schema_version")
    result_schema = payload.get("result_schema_version")
    if input_schema != INPUT_SCHEMA_VERSION:
        raise ProposalValidationError("Unsupported input schema")
    if result_schema != RESULT_SCHEMA_VERSION:
        raise ProposalValidationError("Unsupported result schema")

    return {
        "title": _bounded_text(payload, "title", 3, 120),
        "scientific_purpose": _bounded_text(
            payload, "scientific_purpose", 20, 5000, multiline=True
        ),
        "source_url": _https_url(payload, "source_url", required=True),
        "paper_url": _https_url(payload, "paper_url", required=False),
        "input_schema_version": input_schema,
        "result_schema_version": result_schema,
    }


def _required_pattern(payload, name, pattern, message):
    value = payload.get(name)
    if not isinstance(value, str) or not pattern.fullmatch(value):
        raise ProposalValidationError(message)
    return value


def _required_exact(payload, name, expected, message):
    value = payload.get(name)
    if value != expected:
        raise ProposalValidationError(message)
    return value


def validate_event_payload(payload):
    if not isinstance(payload, dict):
        raise ProposalValidationError("A JSON object is required")
    unknown = set(payload) - EVENT_COMMON_FIELDS - EVENT_EVIDENCE_FIELDS
    if unknown:
        raise ProposalValidationError("Invalid review event fields")

    event_type = payload.get("type")
    if event_type not in VALID_STATES - {"submitted"}:
        raise ProposalValidationError("Invalid review event type")
    expected_revision_id = _bounded_text(payload, "expected_revision_id", 1, 80)
    note = _optional_text(payload, "note", 2000)
    evidence = {}

    if event_type in {"changes_requested", "rejected", "approved"} and not note:
        raise ProposalValidationError("A review note is required")

    if event_type == "approved":
        evidence = {
            "source_commit": _required_pattern(
                payload,
                "source_commit",
                SOURCE_COMMIT_PATTERN,
                "A lowercase immutable source commit is required",
            ),
            "source_sha256": _required_pattern(
                payload,
                "source_sha256",
                SHA256_PATTERN,
                "A lowercase source SHA-256 is required",
            ),
            "reviewed_image_digest": _required_pattern(
                payload,
                "reviewed_image_digest",
                IMAGE_DIGEST_PATTERN,
                "The scanned immutable image digest is required",
            ),
            "security_review_ref": _bounded_text(
                payload, "security_review_ref", 1, 256
            ),
            "security_scan_report_ref": _bounded_text(
                payload, "security_scan_report_ref", 1, 512
            ),
            "security_scan_report_sha256": _required_pattern(
                payload,
                "security_scan_report_sha256",
                SHA256_PATTERN,
                "A lowercase security scan report SHA-256 is required",
            ),
            "security_scan_scanner": _required_pattern(
                payload,
                "security_scan_scanner",
                SCANNER_PATTERN,
                "A valid security scanner name is required",
            ),
            "security_scan_scanner_version": _required_pattern(
                payload,
                "security_scan_scanner_version",
                SCANNER_VERSION_PATTERN,
                "A valid security scanner version is required",
            ),
            "security_scan_policy": _required_exact(
                payload,
                "security_scan_policy",
                SECURITY_SCAN_POLICY,
                "The fail-closed security scan policy is required",
            ),
            "security_scan_completed_at": _required_pattern(
                payload,
                "security_scan_completed_at",
                UTC_TIMESTAMP_PATTERN,
                "A UTC security scan completion time is required",
            ),
            "scientific_review_ref": _bounded_text(
                payload, "scientific_review_ref", 1, 256
            ),
        }
    elif event_type == "published":
        chain_id = payload.get("chain_id")
        if not isinstance(chain_id, int) or isinstance(chain_id, bool) or chain_id <= 0:
            raise ProposalValidationError("A valid publication chain is required")
        evidence = {
            "image_digest": _required_pattern(
                payload,
                "image_digest",
                IMAGE_DIGEST_PATTERN,
                "An immutable image digest is required",
            ),
            "algorithm_did": _required_pattern(
                payload,
                "algorithm_did",
                DID_PATTERN,
                "A valid algorithm DID is required",
            ),
            "service_id": _required_pattern(
                payload,
                "service_id",
                SERVICE_ID_PATTERN,
                "A valid algorithm service ID is required",
            ),
            "chain_id": chain_id,
            "publication_tx_hash": _required_pattern(
                payload,
                "publication_tx_hash",
                TX_HASH_PATTERN,
                "A publication transaction hash is required",
            ),
        }
    elif event_type == "whitelisted":
        evidence = {
            "dataset_did": _required_pattern(
                payload, "dataset_did", DID_PATTERN, "A valid dataset DID is required"
            ),
            "allowlist_tx_hash": _required_pattern(
                payload,
                "allowlist_tx_hash",
                TX_HASH_PATTERN,
                "An allowlist transaction hash is required",
            ),
        }

    allowed = EVENT_COMMON_FIELDS | set(evidence)
    if set(payload) - allowed:
        raise ProposalValidationError("Evidence is not valid for this event type")

    return {
        "type": event_type,
        "expected_revision_id": expected_revision_id,
        "note": note,
        "evidence": evidence,
    }


def parse_pagination(page_value, per_page_value):
    try:
        page = int(page_value)
        per_page = int(per_page_value)
    except (TypeError, ValueError):
        raise ProposalValidationError("Invalid pagination")
    if page < 0 or page > 10000 or per_page < 1 or per_page > 50:
        raise ProposalValidationError("Invalid pagination")
    return page, per_page


def public_proposal(document):
    result = copy.deepcopy(document)
    result.pop("_id", None)
    result.pop("_rev", None)
    result.pop("_attachments", None)
    return result


class AlgorithmProposalWorkflow:
    def __init__(self, dao, clock=None, id_factory=None):
        self.dao = dao
        self.clock = clock or _utc_now
        self.id_factory = id_factory or _new_id

    def create(self, submitter_wallet, payload):
        wallet = normalize_wallet(submitter_wallet)
        content = validate_revision_payload(payload)
        now = self.clock()
        proposal_id = self.id_factory("proposal")
        revision_id = self.id_factory("revision")
        revision = dict(content)
        revision.update(
            {
                "revision_id": revision_id,
                "revision_number": 1,
                "supersedes_revision_id": None,
                "submitter_wallet": wallet,
                "submitted_at": now,
            }
        )
        document = {
            "_id": proposal_id,
            "type": "algorithm_proposal",
            "proposal_id": proposal_id,
            "submitter_wallet": wallet,
            "title": content["title"],
            "status": "submitted",
            "current_revision_id": revision_id,
            "current_revision_number": 1,
            "created_at": now,
            "updated_at": now,
            "revisions": [revision],
            "events": [
                {
                    "event_id": self.id_factory("event"),
                    "type": "submitted",
                    "revision_id": revision_id,
                    "actor_wallet": wallet,
                    "occurred_at": now,
                    "note": None,
                    "evidence": {},
                }
            ],
        }
        self.dao.create(document)
        return public_proposal(document)

    def get_for_actor(self, proposal_id, actor_wallet, is_admin=False):
        proposal_id = normalize_proposal_id(proposal_id)
        wallet = normalize_wallet(actor_wallet)
        document = self.dao.get(proposal_id)
        if not is_admin and document.get("submitter_wallet") != wallet:
            raise ProposalForbiddenError("Proposal access denied")
        return public_proposal(document)

    def list_for_submitter(self, submitter_wallet, page, per_page):
        wallet = normalize_wallet(submitter_wallet)
        rows, has_more = self.dao.list_owned(wallet, page, per_page)
        return self._page(rows, page, per_page, has_more)

    def list_for_admin(self, page, per_page, status=None):
        if status is not None and status not in VALID_STATES:
            raise ProposalValidationError("Invalid proposal status")
        rows, has_more = self.dao.list_queue(page, per_page, status)
        return self._page(rows, page, per_page, has_more)

    def add_revision(
        self, proposal_id, submitter_wallet, payload, expected_revision_id
    ):
        proposal_id = normalize_proposal_id(proposal_id)
        wallet = normalize_wallet(submitter_wallet)
        content = validate_revision_payload(payload)
        expected = self._expected_revision(expected_revision_id)
        now = self.clock()
        new_revision_id = self.id_factory("revision")
        event_id = self.id_factory("event")

        def mutate(document):
            if document.get("submitter_wallet") != wallet:
                raise ProposalForbiddenError("Proposal access denied")
            self._check_expected(document, expected)
            if document.get("status") != "changes_requested":
                raise ProposalConflictError(
                    "A new revision is not allowed in this state"
                )
            if len(document.get("revisions", [])) >= MAX_REVISIONS:
                raise ProposalConflictError("Proposal revision limit reached")
            if len(document.get("events", [])) >= MAX_EVENTS:
                raise ProposalConflictError("Proposal event limit reached")

            revision_number = document["current_revision_number"] + 1
            revision = dict(content)
            revision.update(
                {
                    "revision_id": new_revision_id,
                    "revision_number": revision_number,
                    "supersedes_revision_id": document["current_revision_id"],
                    "submitter_wallet": wallet,
                    "submitted_at": now,
                }
            )
            document["revisions"].append(revision)
            document["events"].append(
                {
                    "event_id": event_id,
                    "type": "submitted",
                    "revision_id": new_revision_id,
                    "actor_wallet": wallet,
                    "occurred_at": now,
                    "note": None,
                    "evidence": {},
                }
            )
            document.update(
                {
                    "title": content["title"],
                    "status": "submitted",
                    "current_revision_id": new_revision_id,
                    "current_revision_number": revision_number,
                    "updated_at": now,
                }
            )
            return document

        return public_proposal(self.dao.mutate(proposal_id, mutate))

    def append_admin_event(self, proposal_id, admin_wallet, payload):
        proposal_id = normalize_proposal_id(proposal_id)
        wallet = normalize_wallet(admin_wallet)
        validated = validate_event_payload(payload)
        now = self.clock()
        event_id = self.id_factory("event")

        def mutate(document):
            self._check_expected(document, validated["expected_revision_id"])
            current = document.get("status")
            target = validated["type"]
            if target not in ADMIN_TRANSITIONS.get(current, set()):
                raise ProposalConflictError(
                    "Transition from {} to {} is not allowed".format(current, target)
                )
            if len(document.get("events", [])) >= MAX_EVENTS:
                raise ProposalConflictError("Proposal event limit reached")
            if target == "published":
                approval = next(
                    (
                        event
                        for event in reversed(document.get("events", []))
                        if event.get("type") == "approved"
                        and event.get("revision_id")
                        == document.get("current_revision_id")
                    ),
                    None,
                )
                reviewed_digest = (
                    (approval or {}).get("evidence", {}).get("reviewed_image_digest")
                )
                if reviewed_digest != validated["evidence"].get("image_digest"):
                    raise ProposalConflictError(
                        "Published image does not match the scanned approval"
                    )
            document["events"].append(
                {
                    "event_id": event_id,
                    "type": target,
                    "revision_id": document["current_revision_id"],
                    "actor_wallet": wallet,
                    "occurred_at": now,
                    "note": validated["note"],
                    "evidence": validated["evidence"],
                }
            )
            document["status"] = target
            document["updated_at"] = now
            return document

        return public_proposal(self.dao.mutate(proposal_id, mutate))

    @staticmethod
    def _expected_revision(value):
        if not isinstance(value, str) or not value or len(value) > 80:
            raise ProposalValidationError("expected_revision_id is required")
        return value

    @staticmethod
    def _check_expected(document, expected_revision_id):
        if document.get("current_revision_id") != expected_revision_id:
            raise ProposalConflictError("The proposal revision has changed")

    @staticmethod
    def _page(rows, page, per_page, has_more):
        return {
            "rows": [public_proposal(row) for row in rows],
            "page": page,
            "per_page": per_page,
            "has_more": bool(has_more),
        }
