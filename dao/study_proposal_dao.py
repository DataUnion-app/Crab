from config import config
from dao.base_dao import BaseDao, DBConflictError, DBResultError
from commands.dataunions.brainstem.study_proposals import (
    StudyProposalConflict,
    StudyProposalNotFound,
)


SUMMARY_FIELDS = [
    "type",
    "schema",
    "proposalId",
    "authorId",
    "title",
    "status",
    "currentRevisionId",
    "currentRevisionNumber",
    "currentRevisionSha256",
    "createdAt",
    "updatedAt",
    "access",
    "revisions",
    "reviews",
    "events",
]


class StudyProposalDao(BaseDao):
    def create(self, document):
        self.save(document["_id"], document)

    def get(self, proposal_id):
        url = self.client.document_url(self.db_name, proposal_id)
        response = self.client.request("GET", url, headers={"Accept": "application/json"})
        if response.status_code == 404:
            raise StudyProposalNotFound("Study proposal not found")
        if response.status_code != 200:
            raise DBResultError(self.db_name, response.text)
        return response.json()

    def mutate(self, proposal_id, mutator):
        self.get(proposal_id)
        try:
            self.mutate_doc(proposal_id, mutator)
        except DBConflictError:
            raise StudyProposalConflict("The study proposal changed concurrently")
        return self.get(proposal_id)

    def list_accessible(self, actor, page, per_page):
        return self._list(
            {
                "type": "brainstem_study_proposal",
                "$or": [
                    {"authorId": actor, "schema": "brainstem.study-proposal/v1"},
                    {"access.ownerId": actor},
                    {"access.collaborators": {"$elemMatch": {"actorId": actor}}},
                ],
                "updatedAt": {"$gt": None},
            },
            page,
            per_page,
        )

    def list_queue(self, page, per_page, status=None):
        selector = {
            "type": "brainstem_study_proposal",
            "status": {"$ne": "draft"},
            "updatedAt": {"$gt": None},
        }
        if status is not None:
            selector["status"] = status
        return self._list(selector, page, per_page)

    def _list(self, selector, page, per_page):
        result = self.query_data(
            {
                "selector": selector,
                "fields": SUMMARY_FIELDS,
                "sort": [{"updatedAt": "desc"}],
                "skip": page * per_page,
                "limit": per_page + 1,
            }
        )["result"]
        return result[:per_page], len(result) > per_page


study_proposal_dao = StudyProposalDao()
study_proposal_dao.set_config(
    config["couchdb"]["user"],
    config["couchdb"]["password"],
    config["couchdb"]["db_host"],
    config["couchdb"].get("studies_db", "brainstem_studies"),
)
