import hashlib
import json
import re
from copy import deepcopy

from config import config
from dao.base_dao import BaseDao, DBConflictError, DBResultError


class StudyStateError(RuntimeError):
    pass


class StudyStateSourceLimitError(StudyStateError):
    pass


class StudyDao(BaseDao):
    @staticmethod
    def _doc_id(user_id):
        return "brainstem_study:{}".format(
            hashlib.sha256(user_id.encode()).hexdigest()
        )

    def get_state(self, user_id):
        exists, value = self.get_if_exists(self._doc_id(user_id))
        return value if exists else None

    def mutate_state(self, user_id, mutator, max_attempts=3):
        doc_id = self._doc_id(user_id)
        url = self.client.document_url(self.db_name, doc_id)
        for _attempt in range(max_attempts):
            response = self.client.request("GET", url)
            if response.status_code == 200:
                current = response.json()
            elif response.status_code == 404:
                current = {
                    "_id": doc_id,
                    "document_type": "brainstem_study_participant_state",
                    "user_id": user_id,
                }
            else:
                raise DBResultError(self.db_name, response.text)
            updated = mutator(deepcopy(current))
            response = self.client.request(
                "PUT",
                url,
                headers={"Content-Type": "application/json"},
                data=json.dumps(updated),
            )
            if response.status_code in {200, 201}:
                updated["_rev"] = response.json()["rev"]
                return updated
            if response.status_code != 409:
                raise DBResultError(self.db_name, response.text)
        raise DBConflictError(self.db_name, doc_id, max_attempts)

    def researcher_projection_states(self, limit=10000):
        if not 1 <= limit <= 10000:
            raise StudyStateError("limit_invalid")
        return self.query_data(
            {
                "selector": {
                    "document_type": "brainstem_study_participant_state"
                },
                "fields": ["enrollment"],
                "limit": limit,
            }
        )["result"]

    def materialization_states(self, offering_id, limit=10000):
        if (
            not isinstance(offering_id, str)
            or not re.fullmatch(r"[a-z0-9][a-z0-9._-]{2,127}", offering_id)
            or not 1 <= limit <= 10001
        ):
            raise StudyStateError("limit_invalid")
        rows = self.query_data(
            {
                "selector": {
                    "document_type": "brainstem_study_participant_state"
                },
                "fields": ["user_id", "offerings"],
                "limit": limit,
            }
        )["result"]
        if len(rows) >= limit:
            raise StudyStateSourceLimitError("source_limit_exceeded")
        return [
            row
            for row in rows
            if isinstance(row, dict)
            and isinstance(row.get("offerings"), dict)
            and isinstance(row["offerings"].get(offering_id), dict)
            and isinstance(
                row["offerings"][offering_id].get("enrollment"), dict
            )
            and row["offerings"][offering_id]["enrollment"].get("state")
            == "active"
        ]

    def generic_operations_metric_states(self, limit=10000):
        if not 1 <= limit <= 10001:
            raise StudyStateError("limit_invalid")
        return self.query_data(
            {
                "selector": {
                    "document_type": "brainstem_study_participant_state"
                },
                "fields": ["user_id", "offerings"],
                "limit": limit,
            }
        )["result"]


study_dao = StudyDao()
study_dao.set_config(
    config["couchdb"]["user"],
    config["couchdb"]["password"],
    config["couchdb"]["db_host"],
    config["couchdb"].get("studies_db", "brainstem_studies"),
)
