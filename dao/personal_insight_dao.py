import hashlib
import hmac

from config import config
from dao.base_dao import BaseDao


class PersonalInsightStateError(RuntimeError):
    pass


def _matches(value, expected):
    return isinstance(value, str) and hmac.compare_digest(value, expected)


class PersonalInsightDao(BaseDao):
    @staticmethod
    def _challenge_doc(slot_id):
        return "personal_insight_challenge:{}".format(slot_id)

    @staticmethod
    def _grant_doc(grant_id):
        return "personal_insight_grant:{}".format(grant_id)

    @staticmethod
    def _capability_doc(capability_id):
        return "personal_insight_capability:{}".format(capability_id)

    def create_or_get_challenge(self, slot_id, data, now):
        doc_id = self._challenge_doc(slot_id)
        exists, current = self.get_if_exists(doc_id)
        if (
            exists
            and current.get("consumed_at") is None
            and current.get("expires_at", 0) > now
        ):
            return current
        if exists:
            data["_rev"] = current["_rev"]
        self.save(doc_id, data)
        return data

    def get_challenge(self, slot_id):
        exists, document = self.get_if_exists(self._challenge_doc(slot_id))
        if not exists:
            raise PersonalInsightStateError("Challenge unavailable")
        return document

    def consume_challenge(self, slot_id, challenge_id, now):
        def consume(document):
            if document.get("challenge_id") != challenge_id:
                raise PersonalInsightStateError("Challenge unavailable")
            if document.get("consumed_at") is not None:
                raise PersonalInsightStateError("Challenge already used")
            if document.get("expires_at", 0) <= now:
                raise PersonalInsightStateError("Challenge expired")
            message = document.pop("message", None)
            address = document.pop("address", None)
            if not isinstance(message, str) or not isinstance(address, str):
                raise PersonalInsightStateError("Challenge unavailable")
            document["message_sha256"] = hashlib.sha256(
                message.encode("utf-8")
            ).hexdigest()
            document["address_sha256"] = hashlib.sha256(
                address.encode("ascii")
            ).hexdigest()
            document["consumed_at"] = now
            return document

        self.mutate_doc(self._challenge_doc(slot_id), consume)

    def save_grant(self, grant_id, data):
        self.save(self._grant_doc(grant_id), data)

    def get_grant(self, grant_id):
        exists, document = self.get_if_exists(self._grant_doc(grant_id))
        if not exists:
            raise PersonalInsightStateError("Grant unavailable")
        return document

    def _mutate_grant(self, grant_id, mutator):
        self.mutate_doc(self._grant_doc(grant_id), mutator)
        return self.get_grant(grant_id)

    def claim_grant(
        self,
        grant_id,
        token_sha256,
        job_id_hash,
        run_id_hash,
        history_id,
        now,
    ):
        def claim(document):
            if not _matches(document.get("token_sha256"), token_sha256):
                raise PersonalInsightStateError("Grant unavailable")
            if document.get("expires_at", 0) <= now:
                raise PersonalInsightStateError("Grant expired")
            bound = document.get("job_id_sha256")
            if bound is not None:
                if (
                    not _matches(bound, job_id_hash)
                    or not _matches(document.get("run_id_sha256"), run_id_hash)
                    or not _matches(document.get("history_id"), history_id)
                ):
                    raise PersonalInsightStateError("Grant already bound")
                if document.get("state") != "claimed":
                    raise PersonalInsightStateError("Grant already used")
                return None
            if document.get("state") != "approved":
                raise PersonalInsightStateError("Grant unavailable")
            document["state"] = "claimed"
            document["job_id_sha256"] = job_id_hash
            document["run_id_sha256"] = run_id_hash
            document["history_id"] = history_id
            document["claimed_at"] = now
            return document

        return self._mutate_grant(grant_id, claim)

    def list_history(self, user_id, origin, limit):
        return self.query_data(
            {
                "selector": {
                    "document_type": "brainstem_personal_insight_grant",
                    "user_id": user_id,
                    "origin": origin,
                    "history_id": {"$regex": "^[0-9a-f]{64}$"},
                },
                "limit": limit,
            }
        )["result"]

    def get_history(self, history_id):
        documents = self.query_data(
            {
                "selector": {
                    "document_type": "brainstem_personal_insight_grant",
                    "history_id": history_id,
                },
                "limit": 2,
            }
        )["result"]
        if len(documents) != 1:
            raise PersonalInsightStateError("History unavailable")
        return documents[0]

    def begin_fetch(self, grant_id, token_sha256, job_id_hash, now):
        def begin(document):
            if not _matches(document.get("token_sha256"), token_sha256):
                raise PersonalInsightStateError("Grant unavailable")
            if document.get("expires_at", 0) <= now:
                raise PersonalInsightStateError("Grant expired")
            if not _matches(document.get("job_id_sha256"), job_id_hash):
                raise PersonalInsightStateError("Grant job mismatch")
            if document.get("state") != "claimed":
                raise PersonalInsightStateError("Dataset already requested")
            document["state"] = "fetching"
            document["fetch_started_at"] = now
            return document

        return self._mutate_grant(grant_id, begin)

    def complete_fetch(
        self,
        grant_id,
        job_id_hash,
        checksum,
        byte_count,
        source_records,
        now,
    ):
        def complete(document):
            if (
                document.get("state") != "fetching"
                or not _matches(document.get("job_id_sha256"), job_id_hash)
            ):
                raise PersonalInsightStateError("Dataset fetch unavailable")
            document["state"] = "fetched"
            document["dataset_sha256"] = checksum
            document["dataset_byte_count"] = byte_count
            document["source_records"] = source_records
            document["fetched_at"] = now
            return document

        return self._mutate_grant(grant_id, complete)

    def complete_run(
        self,
        grant_id,
        token_sha256,
        job_id_hash,
        run_id_hash,
        result_sha256,
        result_expires_at,
        now,
    ):
        def complete(document):
            if (
                not _matches(document.get("token_sha256"), token_sha256)
                or not _matches(document.get("job_id_sha256"), job_id_hash)
                or not _matches(document.get("run_id_sha256"), run_id_hash)
            ):
                raise PersonalInsightStateError("Run unavailable")
            if document.get("state") == "complete":
                if _matches(document.get("result_sha256"), result_sha256):
                    return None
                raise PersonalInsightStateError("Run already completed")
            if document.get("state") != "fetched":
                raise PersonalInsightStateError("Run unavailable")
            document["state"] = "complete"
            document["result_sha256"] = result_sha256
            document["result_expires_at"] = result_expires_at
            document["completed_at"] = now
            return document

        return self._mutate_grant(grant_id, complete)

    def fail_fetch(self, grant_id, job_id_hash, reason, now):
        def fail(document):
            if document.get("state") != "fetching":
                return None
            if not _matches(document.get("job_id_sha256"), job_id_hash):
                raise PersonalInsightStateError("Dataset fetch unavailable")
            document["state"] = "failed"
            document["failure_reason"] = reason
            document["failed_at"] = now
            return document

        return self._mutate_grant(grant_id, fail)

    def save_capability(self, capability_id, data):
        self.save(self._capability_doc(capability_id), data)

    def consume_capability(
        self,
        capability_id,
        token_sha256,
        run_id_hash,
        action,
        now,
    ):
        def consume(document):
            if (
                not _matches(document.get("token_sha256"), token_sha256)
                or not _matches(document.get("run_id_sha256"), run_id_hash)
                or document.get("action") != action
            ):
                raise PersonalInsightStateError("Capability unavailable")
            if document.get("expires_at", 0) <= now:
                raise PersonalInsightStateError("Capability expired")
            if document.get("consumed_at") is not None:
                raise PersonalInsightStateError("Capability already used")
            document["consumed_at"] = now
            return document

        self.mutate_doc(self._capability_doc(capability_id), consume)
        exists, document = self.get_if_exists(self._capability_doc(capability_id))
        if not exists:
            raise PersonalInsightStateError("Capability unavailable")
        return document

    def consume_history_capability(
        self,
        capability_id,
        token_sha256,
        history_id,
        action,
        now,
    ):
        def consume(document):
            if (
                not _matches(document.get("token_sha256"), token_sha256)
                or not _matches(document.get("history_id"), history_id)
                or document.get("action") != action
            ):
                raise PersonalInsightStateError("Capability unavailable")
            if document.get("expires_at", 0) <= now:
                raise PersonalInsightStateError("Capability expired")
            if document.get("consumed_at") is not None:
                raise PersonalInsightStateError("Capability already used")
            document["consumed_at"] = now
            return document

        self.mutate_doc(self._capability_doc(capability_id), consume)
        exists, document = self.get_if_exists(self._capability_doc(capability_id))
        if not exists:
            raise PersonalInsightStateError("Capability unavailable")
        return document


personal_insight_dao = PersonalInsightDao()
personal_insight_dao.set_config(
    config["couchdb"]["user"],
    config["couchdb"]["password"],
    config["couchdb"]["db_host"],
    config["couchdb"]["sessions_db"],
)
