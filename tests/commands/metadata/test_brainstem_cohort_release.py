from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest

from commands.dataunions.brainstem import cohort_release
from commands.dataunions.brainstem.cohort_release import (
    CohortReleaseError,
    CohortReleaseService,
)


CONSENT_VERSION = "brainstem-tos-2026-07"
NOW = datetime(2026, 7, 23, 0, 0, tzinfo=timezone.utc)


class FakeReleaseDao:
    def __init__(self):
        self.documents = {}

    def save(self, doc_id, document):
        if doc_id in self.documents:
            raise RuntimeError("conflict")
        self.documents[doc_id] = deepcopy(document)

    def get_doc_by_id(self, doc_id):
        if doc_id not in self.documents:
            raise RuntimeError("not found")
        return deepcopy(self.documents[doc_id])

    def mutate_doc(self, doc_id, mutator):
        self.documents[doc_id] = mutator(deepcopy(self.documents[doc_id]))
        return deepcopy(self.documents[doc_id])


class FakeUsersDao:
    def __init__(self):
        self.users = {
            "user-a": {
                "_id": "user-a",
                "public_address": "0x" + "a" * 40,
                "usage_flag": "ACCEPTED",
                "guidelines_acceptance_flag": "ACCEPTED",
            },
            "user-b": {
                "_id": "user-b",
                "public_address": "0x" + "b" * 40,
                "usage_flag": "ACCEPTED",
                "guidelines_acceptance_flag": "ACCEPTED",
            },
        }

    def get_doc_by_id(self, user_id):
        if user_id not in self.users:
            raise RuntimeError("not found")
        return deepcopy(self.users[user_id])


class FakeMetadataDao:
    def __init__(self):
        self.last_query = None
        self.documents = [
            {
                "_id": "record-a-0",
                "created_by": "0x" + "a" * 40,
                "content_hash": "a" * 64,
            },
            {
                "_id": "record-b-0",
                "created_by": "0x" + "b" * 40,
                "content_hash": "b" * 64,
            },
        ]

    def iter_query(self, query, batch_size):
        assert batch_size == 500
        self.last_query = deepcopy(query)
        yield from deepcopy(self.documents)


def service():
    return CohortReleaseService(
        FakeReleaseDao(),
        FakeUsersDao(),
        CONSENT_VERSION,
        now=lambda: NOW,
        minimum_release_participants=1,
    )


def test_default_release_floor_rejects_nineteen_participants():
    release_service = CohortReleaseService(
        FakeReleaseDao(), FakeUsersDao(), CONSENT_VERSION, now=lambda: NOW
    )
    with pytest.raises(CohortReleaseError, match="release_privacy_floor"):
        release_service.create(
            ["user-{}".format(index) for index in range(19)],
            "2026-08-01T00:00:00Z",
        )


def test_release_requires_separate_activation_and_can_be_revoked(monkeypatch):
    monkeypatch.setattr(cohort_release.secrets, "token_hex", lambda _size: "a" * 64)
    release_service = service()

    draft = release_service.create(["user-b", "user-a"], "2026-08-01T00:00:00Z")
    assert draft["status"] == "draft"
    assert draft["roster_user_ids"] == ["user-a", "user-b"]
    with pytest.raises(CohortReleaseError, match="release_not_active"):
        release_service.active_member_ids(draft["release_id"])

    active = release_service.activate(draft["release_id"], "legal-review:ticket-123")
    assert active["status"] == "active"
    assert "legal-review:ticket-123" not in str(active)
    assert release_service.active_member_ids(draft["release_id"]) == {
        "user-a",
        "user-b",
    }

    revoked = release_service.revoke(draft["release_id"], "operator-stop:ticket-456")
    assert revoked["status"] == "revoked"
    assert "operator-stop:ticket-456" not in str(revoked)
    with pytest.raises(CohortReleaseError, match="release_not_active"):
        release_service.active_member_ids(draft["release_id"])


def test_activation_rechecks_current_consent(monkeypatch):
    monkeypatch.setattr(cohort_release.secrets, "token_hex", lambda _size: "b" * 64)
    release_service = service()
    draft = release_service.create(["user-a"], "2026-08-01T00:00:00Z")
    release_service.users_dao.users["user-a"]["usage_flag"] = "REJECTED"

    with pytest.raises(CohortReleaseError, match="release_member_ineligible"):
        release_service.activate(draft["release_id"], "legal-review:ticket-123")


def test_release_can_use_a_purpose_specific_consent_checker(monkeypatch):
    monkeypatch.setattr(cohort_release.secrets, "token_hex", lambda _size: "c" * 64)
    release_service = CohortReleaseService(
        FakeReleaseDao(),
        FakeUsersDao(),
        CONSENT_VERSION,
        now=lambda: NOW,
        minimum_release_participants=1,
        purpose="brainstem.full-night-rr-signal-compatibility/v1",
        consent_checker=lambda user: user.get("_id") == "user-a",
    )
    draft = release_service.create(["user-a"], "2026-08-01T00:00:00Z")
    assert release_service.activate(
        draft["release_id"], "study-review:ticket-123"
    )["status"] == "active"


def test_release_revision_can_bind_sleep_records():
    metadata = FakeMetadataDao()
    release_service = CohortReleaseService(
        FakeReleaseDao(),
        FakeUsersDao(),
        CONSENT_VERSION,
        now=lambda: NOW,
        metadata_dao=metadata,
        minimum_release_participants=1,
        purpose="brainstem.full-night-rr-signal-compatibility/v1",
        record_type="sleep",
    )

    release_service.create(["user-a"], "2026-08-01T00:00:00Z")

    assert metadata.last_query["selector"]["record_type"] == "sleep"


@pytest.mark.parametrize(
    "roster",
    [[], ["duplicate", "duplicate"], ["bad\nidentifier"], [1]],
)
def test_invalid_roster_is_rejected_without_creating_a_release(roster):
    release_service = service()
    with pytest.raises(CohortReleaseError, match="release_roster_invalid"):
        release_service.create(roster, "2026-08-01T00:00:00Z")
    assert release_service.release_dao.documents == {}


def test_expired_or_contract_mismatched_release_fails_closed(monkeypatch):
    monkeypatch.setattr(cohort_release.secrets, "token_hex", lambda _size: "c" * 64)
    release_service = service()
    draft = release_service.create(["user-a"], "2026-08-01T00:00:00Z")
    release_id = draft["release_id"]
    doc_id = f"brainstem-c2d-release:{release_id}"

    release_service.release_dao.documents[doc_id]["purpose"] = "other"
    with pytest.raises(CohortReleaseError, match="release_contract_mismatch"):
        release_service.activate(release_id, "legal-review:ticket-123")

    release_service.release_dao.documents[doc_id].update(
        purpose="brainstem.resting-rr/v1",
        status="active",
        activated_at="2026-07-23T00:00:00Z",
        expires_at="2020-01-01T00:00:00Z",
    )
    with pytest.raises(CohortReleaseError, match="release_expired"):
        release_service.active_member_ids(release_id)


def test_release_lifetime_is_bounded_to_fourteen_days():
    release_service = service()
    with pytest.raises(CohortReleaseError, match="release_expired"):
        release_service.create(["user-a"], "2026-08-07T00:00:01Z")


def test_refresh_requires_time_and_distinct_contributors_and_is_idempotent():
    clock = [NOW]
    releases = FakeReleaseDao()
    users = FakeUsersDao()
    metadata = FakeMetadataDao()
    release_service = CohortReleaseService(
        releases,
        users,
        CONSENT_VERSION,
        now=lambda: clock[0],
        metadata_dao=metadata,
        refresh_min_contributors=2,
        refresh_min_age=timedelta(days=1),
        minimum_release_participants=1,
    )
    current = release_service.create(["user-a", "user-b"], "2026-08-01T00:00:00Z")
    release_service.activate(current["release_id"], "legal-review:ticket-123")

    metadata.documents.extend(
        [
            {
                "_id": "record-a-1",
                "created_by": "0x" + "a" * 40,
                "content_hash": "c" * 64,
            },
            {
                "_id": "record-b-1",
                "created_by": "0x" + "b" * 40,
                "content_hash": "d" * 64,
            },
        ]
    )
    clock[0] = NOW + timedelta(hours=12)
    assert release_service.evaluate_refresh(current["release_id"])["state"] == "current"

    metadata.documents = [
        document for document in metadata.documents if document["_id"] != "record-b-1"
    ]
    clock[0] = NOW + timedelta(days=2)
    assert release_service.evaluate_refresh(current["release_id"])["state"] == "current"
    metadata.documents.append(
        {
            "_id": "record-a-2",
            "created_by": "0x" + "a" * 40,
            "content_hash": "e" * 64,
        }
    )
    assert release_service.evaluate_refresh(current["release_id"])["state"] == "current"

    metadata.documents.append(
        {
            "_id": "record-b-1",
            "created_by": "0x" + "b" * 40,
            "content_hash": "d" * 64,
        }
    )
    ready = release_service.evaluate_refresh(current["release_id"])
    repeated = release_service.evaluate_refresh(current["release_id"])
    assert ready == repeated
    assert set(ready) == {"state", "revision", "evaluatedAt"}
    assert ready["state"] == "refresh_available"
    assert ready["evaluatedAt"] == "2026-07-25T00:00:00Z"
    assert len(releases.documents) == 2
    draft = releases.get_doc_by_id(f"brainstem-c2d-release:{ready['revision']}")
    assert draft["status"] == "draft"
    assert draft["parent_release_id"] == current["release_id"]
    assert "compute" not in str(draft).lower()
    users.users["user-a"]["usage_flag"] = "REJECTED"
    assert (
        release_service.evaluate_refresh(current["release_id"])["state"]
        == "unavailable"
    )


@pytest.mark.parametrize("failure", ["withdrawal", "deletion"])
def test_refresh_fails_closed_when_a_participant_becomes_ineligible(failure):
    clock = [NOW]
    releases = FakeReleaseDao()
    users = FakeUsersDao()
    metadata = FakeMetadataDao()
    release_service = CohortReleaseService(
        releases,
        users,
        CONSENT_VERSION,
        now=lambda: clock[0],
        metadata_dao=metadata,
        refresh_min_contributors=2,
        refresh_min_age=timedelta(days=1),
        minimum_release_participants=1,
    )
    current = release_service.create(["user-a", "user-b"], "2026-08-01T00:00:00Z")
    release_service.activate(current["release_id"], "legal-review:ticket-123")
    if failure == "withdrawal":
        users.users["user-a"]["usage_flag"] = "REJECTED"
    else:
        del users.users["user-a"]
    clock[0] = NOW + timedelta(days=2)

    verdict = release_service.evaluate_refresh(current["release_id"])
    assert verdict["state"] == "unavailable"
    assert len(releases.documents) == 1
