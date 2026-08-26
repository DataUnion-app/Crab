"""Bounded study drafting and domain review with no activation transition."""

from copy import deepcopy
from datetime import datetime, timezone
import re
import uuid
from urllib.parse import urlsplit

from commands.dataunions.studies.registry import content_sha256


MAX_REVISIONS = 20
MAX_REVIEWS = 80
MAX_EVENTS = 100
MAX_COLLABORATORS = 12
REVIEW_DOMAINS = {"scientific", "privacy", "security", "ethics"}
REVIEW_DECISIONS = {"approved", "changes_requested"}
COLLABORATOR_ROLES = {"editor", "viewer"}
QUEUE_STATES = {"draft", "submitted", "reviewing", "changes_requested", "review_complete"}
PROPOSAL_ID = re.compile(r"^study_[0-9a-f]{1,64}$")
WALLET = re.compile(r"^0x[0-9a-fA-F]{40}$")
FIELDS = {
    "title",
    "purpose",
    "population",
    "participantBurden",
    "recordings",
    "surveyOutline",
    "schedule",
    "endpoints",
    "analysisPlan",
    "retention",
    "resultReturnPlan",
    "sourcePapers",
    "conflicts",
    "offeringId",
    "releaseVersion",
    "releaseSha256",
}
IDENTIFIER = re.compile(r"^[a-z0-9][a-z0-9._-]{2,127}$")
VERSION = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
REVISION_FIELDS = FIELDS | {
    "proposalId",
    "revisionId",
    "revisionNumber",
    "supersedesRevisionId",
    "authorId",
    "createdAt",
    "revisionSha256",
}
REVIEW_FIELDS = {
    "reviewId",
    "revisionId",
    "revisionSha256",
    "domain",
    "decision",
    "reviewerId",
    "note",
    "evidenceSha256",
    "occurredAt",
    "decisionSha256",
}
COLLABORATOR_FIELDS = {"actorId", "role", "addedBy", "addedAt"}
ACCESS_FIELDS = {"ownerId", "version", "collaborators", "accessSha256"}


class StudyProposalError(Exception):
    status_code = 400

    def __init__(self, message):
        self.message = message
        super().__init__(message)


class StudyProposalForbidden(StudyProposalError):
    status_code = 403


class StudyProposalNotFound(StudyProposalError):
    status_code = 404


class StudyProposalConflict(StudyProposalError):
    status_code = 409


class StudyProposalPayloadTooLarge(StudyProposalError):
    status_code = 413


def _now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _new_id(prefix):
    return "{}_{}".format(prefix, uuid.uuid4().hex)


def normalize_actor(value):
    if not isinstance(value, str) or not WALLET.fullmatch(value):
        raise StudyProposalError("Invalid researcher identity")
    return value.lower()


def normalize_proposal_id(value):
    if not isinstance(value, str) or not PROPOSAL_ID.fullmatch(value):
        raise StudyProposalError("Invalid study proposal ID")
    return value


def _text(payload, name, minimum=1, maximum=4000):
    value = payload.get(name)
    if not isinstance(value, str):
        raise StudyProposalError("{} must be text".format(name))
    value = value.strip()
    if not minimum <= len(value) <= maximum:
        raise StudyProposalError("{} has an invalid length".format(name))
    if any(ord(character) < 32 and character not in "\n\t" for character in value):
        raise StudyProposalError("{} contains control characters".format(name))
    return value


def _source_papers(value):
    if not isinstance(value, list) or not 1 <= len(value) <= 20:
        raise StudyProposalError("sourcePapers must contain 1 to 20 HTTPS references")
    normalized = []
    for item in value:
        if not isinstance(item, str) or not 1 <= len(item) <= 2048:
            raise StudyProposalError("sourcePapers contains an invalid reference")
        parsed = urlsplit(item)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.fragment
        ):
            raise StudyProposalError("sourcePapers must use public HTTPS references")
        normalized.append(item)
    if len(set(normalized)) != len(normalized):
        raise StudyProposalError("sourcePapers contains duplicates")
    return normalized


def _identifier(payload, name):
    value = payload.get(name)
    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
        raise StudyProposalError("{} is invalid".format(name))
    return value


def _version(payload, name):
    value = payload.get(name)
    if not isinstance(value, str) or not VERSION.fullmatch(value):
        raise StudyProposalError("{} is invalid".format(name))
    return value


def _sha256(payload, name):
    value = payload.get(name)
    if not isinstance(value, str) or not SHA256.fullmatch(value):
        raise StudyProposalError("{} is invalid".format(name))
    return value


def validate_revision(payload):
    if not isinstance(payload, dict) or set(payload) != FIELDS:
        raise StudyProposalError("Invalid study proposal fields")
    result = {
        "title": _text(payload, "title", 3, 160),
        "purpose": _text(payload, "purpose", 20, 4000),
        "population": _text(payload, "population", 10, 4000),
        "participantBurden": _text(payload, "participantBurden", 10, 4000),
        "recordings": _text(payload, "recordings", 10, 4000),
        "surveyOutline": _text(payload, "surveyOutline", 10, 4000),
        "schedule": _text(payload, "schedule", 5, 2000),
        "endpoints": _text(payload, "endpoints", 10, 4000),
        "analysisPlan": _text(payload, "analysisPlan", 20, 8000),
        "retention": _text(payload, "retention", 10, 4000),
        "resultReturnPlan": _text(payload, "resultReturnPlan", 10, 4000),
        "sourcePapers": _source_papers(payload["sourcePapers"]),
        "conflicts": _text(payload, "conflicts", 2, 4000),
        "offeringId": _identifier(payload, "offeringId"),
        "releaseVersion": _version(payload, "releaseVersion"),
        "releaseSha256": _sha256(payload, "releaseSha256"),
    }
    return result


def _with_commitment(value, field):
    committed = deepcopy(value)
    committed[field] = content_sha256(committed)
    return committed


def _access(owner, version, collaborators):
    return _with_commitment(
        {
            "ownerId": owner,
            "version": version,
            "collaborators": collaborators,
        },
        "accessSha256",
    )


def _stored_actor(value, message):
    try:
        return normalize_actor(value)
    except StudyProposalError as error:
        raise StudyProposalConflict(message) from error


def validate_stored_revision(value):
    if not isinstance(value, dict) or set(value) != REVISION_FIELDS:
        raise StudyProposalConflict("Stored study revision commitment is invalid")
    stored_content = {key: value[key] for key in FIELDS}
    try:
        normalized_content = validate_revision(stored_content)
    except StudyProposalError as error:
        raise StudyProposalConflict(
            "Stored study revision commitment is invalid"
        ) from error
    if normalized_content != stored_content or _stored_actor(
        value.get("authorId"), "Stored study revision commitment is invalid"
    ) != value.get("authorId"):
        raise StudyProposalConflict("Stored study revision commitment is invalid")
    if (
        not isinstance(value.get("revisionId"), str)
        or not 1 <= len(value["revisionId"]) <= 80
        or not isinstance(value.get("revisionNumber"), int)
        or value["revisionNumber"] < 1
        or (
            value.get("supersedesRevisionId") is not None
            and not isinstance(value["supersedesRevisionId"], str)
        )
        or not isinstance(value.get("createdAt"), str)
        or not value["createdAt"]
    ):
        raise StudyProposalConflict("Stored study revision commitment is invalid")
    supplied = value.get("revisionSha256")
    unsigned = {
        key: deepcopy(item)
        for key, item in value.items()
        if key != "revisionSha256"
    }
    if not isinstance(supplied, str) or not SHA256.fullmatch(supplied):
        raise StudyProposalConflict("Stored study revision commitment is invalid")
    if supplied != content_sha256(unsigned):
        raise StudyProposalConflict("Stored study revision commitment is invalid")
    return value


def validate_stored_review(value):
    if not isinstance(value, dict) or set(value) != REVIEW_FIELDS:
        raise StudyProposalConflict("Stored study decision commitment is invalid")
    if (
        not isinstance(value.get("reviewId"), str)
        or not value["reviewId"]
        or not isinstance(value.get("revisionId"), str)
        or not value["revisionId"]
        or not isinstance(value.get("revisionSha256"), str)
        or not SHA256.fullmatch(value["revisionSha256"])
        or value.get("domain") not in REVIEW_DOMAINS
        or value.get("decision") not in REVIEW_DECISIONS
        or not isinstance(value.get("note"), str)
        or not 3 <= len(value["note"]) <= 4000
        or not isinstance(value.get("evidenceSha256"), str)
        or not SHA256.fullmatch(value["evidenceSha256"])
        or not isinstance(value.get("occurredAt"), str)
        or not value["occurredAt"]
        or _stored_actor(
            value.get("reviewerId"),
            "Stored study decision commitment is invalid",
        )
        != value.get("reviewerId")
    ):
        raise StudyProposalConflict("Stored study decision commitment is invalid")
    supplied = value.get("decisionSha256")
    unsigned = {
        key: deepcopy(item)
        for key, item in value.items()
        if key != "decisionSha256"
    }
    if not isinstance(supplied, str) or not SHA256.fullmatch(supplied):
        raise StudyProposalConflict("Stored study decision commitment is invalid")
    if supplied != content_sha256(unsigned):
        raise StudyProposalConflict("Stored study decision commitment is invalid")
    return value


def validate_stored_access(value):
    if not isinstance(value, dict) or set(value) != ACCESS_FIELDS:
        raise StudyProposalConflict("Stored study access commitment is invalid")
    owner = _stored_actor(
        value.get("ownerId"), "Stored study access commitment is invalid"
    )
    collaborators = value.get("collaborators")
    if (
        owner != value.get("ownerId")
        or not isinstance(value.get("version"), int)
        or value["version"] < 1
        or not isinstance(collaborators, list)
        or len(collaborators) > MAX_COLLABORATORS
    ):
        raise StudyProposalConflict("Stored study access commitment is invalid")
    actors = set()
    for collaborator in collaborators:
        if not isinstance(collaborator, dict) or set(collaborator) != COLLABORATOR_FIELDS:
            raise StudyProposalConflict("Stored study access commitment is invalid")
        actor = _stored_actor(
            collaborator.get("actorId"), "Stored study access commitment is invalid"
        )
        added_by = _stored_actor(
            collaborator.get("addedBy"), "Stored study access commitment is invalid"
        )
        if (
            actor != collaborator.get("actorId")
            or actor == owner
            or actor in actors
            or collaborator.get("role") not in COLLABORATOR_ROLES
            or added_by != owner
            or added_by != collaborator.get("addedBy")
            or not isinstance(collaborator.get("addedAt"), str)
            or not collaborator["addedAt"]
        ):
            raise StudyProposalConflict("Stored study access commitment is invalid")
        actors.add(actor)
    if collaborators != sorted(collaborators, key=lambda item: item["actorId"]):
        raise StudyProposalConflict("Stored study access commitment is invalid")
    supplied = value.get("accessSha256")
    unsigned = {
        key: deepcopy(item)
        for key, item in value.items()
        if key != "accessSha256"
    }
    if (
        not isinstance(supplied, str)
        or not SHA256.fullmatch(supplied)
        or supplied != content_sha256(unsigned)
    ):
        raise StudyProposalConflict("Stored study access commitment is invalid")
    return value


def proposal_role(document, actor):
    actor = normalize_actor(actor)
    access = document.get("access")
    if document.get("schema") == "brainstem.study-proposal/v1":
        return "owner" if document.get("authorId") == actor else None
    validate_stored_access(access)
    if access["ownerId"] == actor:
        return "owner"
    for collaborator in access["collaborators"]:
        if collaborator["actorId"] == actor:
            return collaborator["role"]
    return None


def proposal_contributors(document):
    contributors = {
        document.get("authorId"),
        *[item.get("authorId") for item in document.get("revisions", [])],
    }
    access = document.get("access")
    if isinstance(access, dict):
        contributors.add(access.get("ownerId"))
        contributors.update(
            item.get("actorId") for item in access.get("collaborators", [])
        )
    contributors.update(
        item.get("subjectId")
        for item in document.get("events", [])
        if item.get("type", "").startswith("collaborator_")
    )
    return contributors


def validate_stored_proposal(document):
    revisions = document.get("revisions")
    reviews = document.get("reviews")
    if not isinstance(revisions, list) or not revisions or not isinstance(reviews, list):
        raise StudyProposalConflict("Stored study proposal commitment is invalid")
    schema = document.get("schema")
    if schema not in {
        "brainstem.study-proposal/v1",
        "brainstem.study-proposal/v2",
    }:
        raise StudyProposalConflict("Stored study proposal commitment is invalid")
    author = _stored_actor(
        document.get("authorId"), "Stored study proposal commitment is invalid"
    )
    if author != document.get("authorId"):
        raise StudyProposalConflict("Stored study proposal commitment is invalid")
    if schema == "brainstem.study-proposal/v2":
        validate_stored_access(document.get("access"))
    elif "access" in document:
        raise StudyProposalConflict("Stored study proposal commitment is invalid")
    for revision in revisions:
        validate_stored_revision(revision)
    for review in reviews:
        validate_stored_review(review)
    for index, revision in enumerate(revisions):
        expected_supersedes = revisions[index - 1]["revisionId"] if index else None
        if (
            revision["revisionNumber"] != index + 1
            or revision["supersedesRevisionId"] != expected_supersedes
            or revision["proposalId"] != document.get("proposalId")
            or (
                schema == "brainstem.study-proposal/v1"
                and revision["authorId"] != document.get("authorId")
            )
        ):
            raise StudyProposalConflict("Stored study revision commitment is invalid")
    revision_commitments = {
        revision["revisionId"]: revision["revisionSha256"] for revision in revisions
    }
    if any(
        revision_commitments.get(review["revisionId"]) != review["revisionSha256"]
        for review in reviews
    ):
        raise StudyProposalConflict("Stored study decision commitment is invalid")
    current = revisions[-1]
    if (
        document.get("currentRevisionId") != current["revisionId"]
        or document.get("currentRevisionNumber") != current["revisionNumber"]
        or document.get("currentRevisionSha256") != current["revisionSha256"]
        or document.get("title") != current["title"]
        or (
            schema == "brainstem.study-proposal/v1"
            and document.get("authorId") != current["authorId"]
        )
    ):
        raise StudyProposalConflict("Stored study proposal commitment is invalid")
    return document


def parse_page(page_value, per_page_value):
    try:
        page = int(page_value)
        per_page = int(per_page_value)
    except (TypeError, ValueError):
        raise StudyProposalError("Invalid pagination")
    if page < 0 or page > 10000 or per_page < 1 or per_page > 50:
        raise StudyProposalError("Invalid pagination")
    return page, per_page


def public_proposal(value):
    result = deepcopy(value)
    for key in ("_id", "_rev", "_attachments"):
        result.pop(key, None)
    return result


def reviewed_revision_binding(
    document,
    proposal_id,
    revision_id,
    revision_sha256,
    offering_id,
    release_version,
    release_sha256,
):
    """Return the non-identifying commitments required to run one reviewed revision."""
    normalize_proposal_id(proposal_id)
    if not isinstance(revision_id, str) or not re.fullmatch(
        r"^revision_[0-9a-f]{1,64}$", revision_id
    ):
        raise StudyProposalError("Invalid study revision ID")
    if not isinstance(revision_sha256, str) or not SHA256.fullmatch(revision_sha256):
        raise StudyProposalError("Invalid study revision commitment")
    if (
        not isinstance(release_version, str)
        or not VERSION.fullmatch(release_version)
        or not isinstance(release_sha256, str)
        or not SHA256.fullmatch(release_sha256)
    ):
        raise StudyProposalError("Invalid study release binding")
    validate_stored_proposal(document)
    current = document["revisions"][-1]
    reviews = [
        review
        for review in document["reviews"]
        if review["revisionId"] == revision_id and review["decision"] == "approved"
    ]
    if (
        document["proposalId"] != proposal_id
        or document["status"] != "review_complete"
        or document["currentRevisionId"] != revision_id
        or document["currentRevisionSha256"] != revision_sha256
        or current["offeringId"] != offering_id
        or current["releaseVersion"] != release_version
        or current["releaseSha256"] != release_sha256
        or {review["domain"] for review in reviews} != REVIEW_DOMAINS
        or len({review["reviewerId"] for review in reviews}) != len(REVIEW_DOMAINS)
    ):
        raise StudyProposalConflict("The study revision is not approved for compute")
    return {
        "proposalId": proposal_id,
        "revisionId": revision_id,
        "revisionSha256": revision_sha256,
        "releaseVersion": release_version,
        "releaseSha256": release_sha256,
        "reviewDecisions": [
            {
                "domain": review["domain"],
                "decisionSha256": review["decisionSha256"],
            }
            for review in sorted(reviews, key=lambda item: item["domain"])
        ],
    }


class StudyProposalWorkflow:
    def __init__(self, dao, clock=None, id_factory=None):
        self.dao = dao
        self.clock = clock or _now
        self.id_factory = id_factory or _new_id

    @staticmethod
    def _expected(value):
        if not isinstance(value, str) or not 1 <= len(value) <= 80:
            raise StudyProposalError("expectedRevisionId is required")
        return value

    @staticmethod
    def _check(document, expected_id, expected_sha256):
        validate_stored_proposal(document)
        current = document["revisions"][-1]
        if (
            document.get("currentRevisionId") != expected_id
            or current.get("revisionSha256") != expected_sha256
        ):
            raise StudyProposalConflict("The study proposal changed concurrently")

    def create(self, author, payload):
        author = normalize_actor(author)
        content = validate_revision(payload)
        now = self.clock()
        proposal_id = self.id_factory("study")
        revision_id = self.id_factory("revision")
        if not PROPOSAL_ID.fullmatch(proposal_id):
            raise RuntimeError("invalid generated study proposal ID")
        revision = _with_commitment({
            **content,
            "proposalId": proposal_id,
            "revisionId": revision_id,
            "revisionNumber": 1,
            "supersedesRevisionId": None,
            "authorId": author,
            "createdAt": now,
        }, "revisionSha256")
        document = {
            "_id": proposal_id,
            "type": "brainstem_study_proposal",
            "schema": "brainstem.study-proposal/v2",
            "proposalId": proposal_id,
            "authorId": author,
            "title": content["title"],
            "status": "draft",
            "currentRevisionId": revision_id,
            "currentRevisionNumber": 1,
            "currentRevisionSha256": revision["revisionSha256"],
            "createdAt": now,
            "updatedAt": now,
            "access": _access(author, 1, []),
            "revisions": [revision],
            "reviews": [],
            "events": [
                {
                    "eventId": self.id_factory("event"),
                    "type": "draft_created",
                    "revisionId": revision_id,
                    "actorId": author,
                    "occurredAt": now,
                }
            ],
        }
        self.dao.create(document)
        return public_proposal(document)

    def get(self, proposal_id, actor, can_review=False):
        proposal_id = normalize_proposal_id(proposal_id)
        actor = normalize_actor(actor)
        document = self.dao.get(proposal_id)
        validate_stored_proposal(document)
        if not can_review and proposal_role(document, actor) is None:
            raise StudyProposalForbidden("Study proposal access denied")
        return public_proposal(document)

    def list_accessible(self, actor, page, per_page):
        actor = normalize_actor(actor)
        rows, has_more = self.dao.list_accessible(actor, page, per_page)
        return self._page(rows, page, per_page, has_more)

    def list_queue(self, page, per_page, status=None):
        if status is not None and status not in QUEUE_STATES - {"draft"}:
            raise StudyProposalError("Invalid study proposal status")
        rows, has_more = self.dao.list_queue(page, per_page, status)
        return self._page(rows, page, per_page, has_more)

    def add_revision(
        self,
        proposal_id,
        author,
        payload,
        expected_revision_id,
        expected_revision_sha256,
    ):
        proposal_id = normalize_proposal_id(proposal_id)
        author = normalize_actor(author)
        content = validate_revision(payload)
        expected = self._expected(expected_revision_id)
        expected_sha256 = self._expected_sha256(expected_revision_sha256)
        now = self.clock()
        revision_id = self.id_factory("revision")

        def mutate(document):
            if proposal_role(document, author) not in {"owner", "editor"}:
                raise StudyProposalForbidden("Study proposal access denied")
            self._check(document, expected, expected_sha256)
            if document.get("status") not in {"draft", "changes_requested"}:
                raise StudyProposalConflict("A revision is not allowed in this state")
            if len(document.get("revisions", [])) >= MAX_REVISIONS:
                raise StudyProposalConflict("Study proposal revision limit reached")
            if len(document.get("events", [])) >= MAX_EVENTS:
                raise StudyProposalConflict("Study proposal event limit reached")
            revision_number = document["currentRevisionNumber"] + 1
            document["revisions"].append(
                _with_commitment({
                    **content,
                    "proposalId": proposal_id,
                    "revisionId": revision_id,
                    "revisionNumber": revision_number,
                    "supersedesRevisionId": document["currentRevisionId"],
                    "authorId": author,
                    "createdAt": now,
                }, "revisionSha256")
            )
            document["events"].append(
                {
                    "eventId": self.id_factory("event"),
                    "type": "revision_created",
                    "revisionId": revision_id,
                    "actorId": author,
                    "occurredAt": now,
                }
            )
            document.update(
                {
                    "title": content["title"],
                    "status": "draft",
                    "currentRevisionId": revision_id,
                    "currentRevisionNumber": revision_number,
                    "currentRevisionSha256": document["revisions"][-1][
                        "revisionSha256"
                    ],
                    "updatedAt": now,
                }
            )
            return document

        return public_proposal(self.dao.mutate(proposal_id, mutate))

    def set_collaborator(
        self,
        proposal_id,
        owner,
        actor,
        role,
        expected_access_version,
    ):
        proposal_id = normalize_proposal_id(proposal_id)
        owner = normalize_actor(owner)
        actor = normalize_actor(actor)
        if role is not None and role not in COLLABORATOR_ROLES:
            raise StudyProposalError("Invalid study collaborator role")
        if not isinstance(expected_access_version, int) or expected_access_version < 1:
            raise StudyProposalError("expectedAccessVersion is required")
        now = self.clock()

        def mutate(document):
            validate_stored_proposal(document)
            if document.get("schema") != "brainstem.study-proposal/v2":
                raise StudyProposalConflict("Study ownership is not bound")
            access = document["access"]
            if access["ownerId"] != owner:
                raise StudyProposalForbidden("Only the study owner can manage access")
            if actor == owner:
                raise StudyProposalError("The study owner cannot be a collaborator")
            if access["version"] != expected_access_version:
                raise StudyProposalConflict("The study access list changed concurrently")
            if document.get("status") not in {"draft", "changes_requested"}:
                raise StudyProposalConflict("Study access cannot change in this state")
            current = {
                item["actorId"]: deepcopy(item)
                for item in access["collaborators"]
            }
            previous = current.get(actor)
            if role is None:
                if previous is None:
                    return document
                current.pop(actor)
                event_type = "collaborator_removed"
            else:
                if previous is not None and previous["role"] == role:
                    return document
                if previous is None and len(current) >= MAX_COLLABORATORS:
                    raise StudyProposalConflict("Study collaborator limit reached")
                current[actor] = {
                    "actorId": actor,
                    "role": role,
                    "addedBy": owner,
                    "addedAt": now,
                }
                event_type = (
                    "collaborator_added" if previous is None else "collaborator_changed"
                )
            if len(document.get("events", [])) >= MAX_EVENTS:
                raise StudyProposalConflict("Study proposal event limit reached")
            document["access"] = _access(
                owner,
                access["version"] + 1,
                sorted(current.values(), key=lambda item: item["actorId"]),
            )
            event = {
                "eventId": self.id_factory("event"),
                "type": event_type,
                "revisionId": document["currentRevisionId"],
                "actorId": owner,
                "subjectId": actor,
                "occurredAt": now,
            }
            if role is not None:
                event["role"] = role
            document["events"].append(event)
            document["updatedAt"] = now
            return document

        return public_proposal(self.dao.mutate(proposal_id, mutate))

    def bind_legacy_owner(
        self,
        proposal_id,
        owner,
        old_author,
        offering_id,
        expected_revision_id,
        expected_revision_sha256,
    ):
        proposal_id = normalize_proposal_id(proposal_id)
        owner = normalize_actor(owner)
        old_author = normalize_actor(old_author)
        expected = self._expected(expected_revision_id)
        expected_sha256 = self._expected_sha256(expected_revision_sha256)
        now = self.clock()

        def mutate(document):
            validate_stored_proposal(document)
            if (
                document.get("schema") != "brainstem.study-proposal/v1"
                or document.get("authorId") != old_author
                or document.get("status") != "draft"
                or document["revisions"][-1].get("offeringId") != offering_id
            ):
                raise StudyProposalConflict("Legacy study ownership cannot be bound")
            self._check(document, expected, expected_sha256)
            if len(document.get("events", [])) >= MAX_EVENTS:
                raise StudyProposalConflict("Study proposal event limit reached")
            document["schema"] = "brainstem.study-proposal/v2"
            document["access"] = _access(owner, 1, [])
            document["events"].append(
                {
                    "eventId": self.id_factory("event"),
                    "type": "owner_bound",
                    "revisionId": document["currentRevisionId"],
                    "actorId": owner,
                    "subjectId": owner,
                    "occurredAt": now,
                }
            )
            document["updatedAt"] = now
            return document

        return public_proposal(self.dao.mutate(proposal_id, mutate))

    @staticmethod
    def _expected_sha256(value):
        if not isinstance(value, str) or not SHA256.fullmatch(value):
            raise StudyProposalError("expectedRevisionSha256 is required")
        return value

    def submit(
        self,
        proposal_id,
        author,
        expected_revision_id,
        expected_revision_sha256,
    ):
        proposal_id = normalize_proposal_id(proposal_id)
        author = normalize_actor(author)
        expected = self._expected(expected_revision_id)
        expected_sha256 = self._expected_sha256(expected_revision_sha256)
        now = self.clock()

        def mutate(document):
            if proposal_role(document, author) != "owner":
                raise StudyProposalForbidden("Study proposal access denied")
            self._check(document, expected, expected_sha256)
            if document.get("status") != "draft":
                raise StudyProposalConflict("Only a draft can be submitted")
            if len(document.get("events", [])) >= MAX_EVENTS:
                raise StudyProposalConflict("Study proposal event limit reached")
            document["status"] = "submitted"
            document["updatedAt"] = now
            document["events"].append(
                {
                    "eventId": self.id_factory("event"),
                    "type": "submitted",
                    "revisionId": document["currentRevisionId"],
                    "actorId": author,
                    "occurredAt": now,
                }
            )
            return document

        return public_proposal(self.dao.mutate(proposal_id, mutate))

    def review(
        self,
        proposal_id,
        reviewer,
        domain,
        decision,
        expected_revision_id,
        expected_revision_sha256,
        note,
        evidence_sha256,
    ):
        proposal_id = normalize_proposal_id(proposal_id)
        reviewer = normalize_actor(reviewer)
        expected = self._expected(expected_revision_id)
        expected_sha256 = self._expected_sha256(expected_revision_sha256)
        if domain not in REVIEW_DOMAINS or decision not in REVIEW_DECISIONS:
            raise StudyProposalError("Invalid study review")
        note = _text({"note": note}, "note", 3, 4000)
        evidence_sha256 = _sha256(
            {"evidenceSha256": evidence_sha256}, "evidenceSha256"
        )
        now = self.clock()

        def mutate(document):
            self._check(document, expected, expected_sha256)
            if document.get("status") not in {"submitted", "reviewing"}:
                raise StudyProposalConflict("Review is not allowed in this state")
            revision_id = document["currentRevisionId"]
            if reviewer in proposal_contributors(document):
                raise StudyProposalForbidden("Authors cannot review their own proposal")
            current_reviews = [
                item
                for item in document.get("reviews", [])
                if item.get("revisionId") == revision_id
            ]
            if any(item.get("reviewerId") == reviewer for item in current_reviews):
                raise StudyProposalConflict(
                    "Each review domain requires a different reviewer"
                )
            if any(
                item.get("revisionId") == revision_id and item.get("domain") == domain
                for item in current_reviews
            ):
                raise StudyProposalConflict("This review domain is already recorded")
            if len(document.get("events", [])) >= MAX_EVENTS:
                raise StudyProposalConflict("Study proposal event limit reached")
            if len(document.get("reviews", [])) >= MAX_REVIEWS:
                raise StudyProposalConflict("Study proposal review limit reached")
            revision_sha256 = document["revisions"][-1]["revisionSha256"]
            review = _with_commitment({
                "reviewId": self.id_factory("review"),
                "revisionId": revision_id,
                "revisionSha256": revision_sha256,
                "domain": domain,
                "decision": decision,
                "reviewerId": reviewer,
                "note": note,
                "evidenceSha256": evidence_sha256,
                "occurredAt": now,
            }, "decisionSha256")
            document.setdefault("reviews", []).append(review)
            document["events"].append(
                {
                    "eventId": self.id_factory("event"),
                    "type": "domain_reviewed",
                    "revisionId": revision_id,
                    "actorId": reviewer,
                    "domain": domain,
                    "decision": decision,
                    "occurredAt": now,
                }
            )
            current = current_reviews + [review]
            if decision == "changes_requested":
                status = "changes_requested"
            elif {item["domain"] for item in current if item["decision"] == "approved"} == REVIEW_DOMAINS:
                status = "review_complete"
            else:
                status = "reviewing"
            document["status"] = status
            document["updatedAt"] = now
            return document

        return public_proposal(self.dao.mutate(proposal_id, mutate))

    @staticmethod
    def _page(rows, page, per_page, has_more):
        for row in rows:
            validate_stored_proposal(row)
        return {
            "rows": [public_proposal(row) for row in rows],
            "page": page,
            "perPage": per_page,
            "hasMore": has_more,
        }
