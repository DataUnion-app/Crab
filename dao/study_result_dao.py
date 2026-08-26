import json
from copy import deepcopy

from config import config
from dao.base_dao import BaseDao, DBResultError
from commands.dataunions.studies.registry import content_sha256
from commands.dataunions.brainstem.study_results import StudyResultError


class StudyResultDao(BaseDao):
    MAX_APPEND_ATTEMPTS = 5

    @staticmethod
    def _prefix(proposal_id):
        return "brainstem-study-result:{}:".format(proposal_id)

    def get(self, proposal_id, job_id_hash):
        rows = self.query_data(
            {
                "selector": {
                    "type": "brainstem_study_result",
                    "proposalId": proposal_id,
                    "jobIdHash": job_id_hash,
                },
                "limit": 2,
            }
        )["result"]
        if len(rows) > 1:
            raise StudyResultError("study_result_job_reused", 409)
        return rows[0] if rows else None

    def append(self, document):
        existing = self.get(document["proposalId"], document["jobIdHash"])
        if existing is not None:
            return self._same_job(existing, document)
        for _attempt in range(self.MAX_APPEND_ATTEMPTS):
            latest = self.list(document["proposalId"], 1)
            version = latest[0]["resultVersion"] + 1 if latest else 1
            stored = deepcopy(document)
            stored.update(
                {
                    "_id": "{}{:06d}".format(
                        self._prefix(document["proposalId"]), version
                    ),
                    "resultVersion": version,
                    "supersedesResultId": latest[0]["resultId"] if latest else None,
                }
            )
            stored["receiptSha256"] = content_sha256(
                {key: value for key, value in stored.items() if key != "_id"}
            )
            response = self.client.request(
                "PUT",
                self.client.document_url(self.db_name, stored["_id"]),
                headers={"Content-Type": "application/json"},
                data=json.dumps(stored),
            )
            if response.status_code in {200, 201}:
                return stored
            if response.status_code != 409:
                raise DBResultError(self.db_name, response.text)
            conflicting = self.get(document["proposalId"], document["jobIdHash"])
            if conflicting is not None:
                return self._same_job(conflicting, document)
        raise StudyResultError("study_result_concurrent_update", 409)

    @staticmethod
    def _same_job(existing, document):
        private = {
            "_id",
            "_rev",
            "resultVersion",
            "supersedesResultId",
            "receiptSha256",
            "resultId",
        }
        comparable = {
            key: value for key, value in existing.items() if key not in private
        }
        candidate = {
            key: value for key, value in document.items() if key not in private
        }
        if comparable != candidate:
            raise StudyResultError("study_result_job_reused", 409)
        return existing

    def list(self, proposal_id, limit):
        prefix = self._prefix(proposal_id)
        response = self.client.request(
            "GET",
            "{}/_all_docs".format(self.base_url),
            params={
                "include_docs": "true",
                "descending": "true",
                "startkey": json.dumps(prefix + "\uffff"),
                "endkey": json.dumps(prefix),
                "limit": limit,
            },
        )
        if response.status_code != 200:
            raise DBResultError(self.db_name, response.text)
        return [row["doc"] for row in response.json().get("rows", [])]


study_result_dao = StudyResultDao()
study_result_dao.set_config(
    config["couchdb"]["user"],
    config["couchdb"]["password"],
    config["couchdb"]["db_host"],
    config["couchdb"].get("studies_db", "brainstem_studies"),
)
