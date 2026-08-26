from config import config
from dao.base_dao import BaseDao, DBConflictError, DBResultError
from commands.dataunions.brainstem.algorithm_proposals import (
    ProposalConflictError,
    ProposalNotFoundError,
)


SUMMARY_FIELDS = [
    "proposal_id",
    "submitter_wallet",
    "title",
    "status",
    "current_revision_id",
    "current_revision_number",
    "created_at",
    "updated_at",
]


class AlgorithmProposalDao(BaseDao):
    def create(self, document):
        self.save(document["_id"], document)

    def get(self, proposal_id):
        url = self.client.document_url(self.db_name, proposal_id)
        response = self.client.request(
            "GET", url, headers={"Accept": "application/json"}
        )
        if response.status_code == 404:
            raise ProposalNotFoundError("Proposal not found")
        if response.status_code != 200:
            raise DBResultError(self.db_name, response.text)
        return response.json()

    def mutate(self, proposal_id, mutator):
        self.get(proposal_id)
        try:
            self.mutate_doc(proposal_id, mutator)
        except DBConflictError:
            raise ProposalConflictError("The proposal changed concurrently")
        return self.get(proposal_id)

    def list_owned(self, submitter_wallet, page, per_page):
        selector = {
            "type": "algorithm_proposal",
            "submitter_wallet": submitter_wallet,
            "updated_at": {"$gt": None},
        }
        return self._list(selector, page, per_page)

    def list_queue(self, page, per_page, status=None):
        selector = {
            "type": "algorithm_proposal",
            "updated_at": {"$gt": None},
        }
        if status is not None:
            selector["status"] = status
        return self._list(selector, page, per_page)

    def _list(self, selector, page, per_page):
        query = {
            "selector": selector,
            "fields": SUMMARY_FIELDS,
            "sort": [{"updated_at": "desc"}],
            "skip": page * per_page,
            "limit": per_page + 1,
        }
        result = self.query_data(query)["result"]
        return result[:per_page], len(result) > per_page


algorithm_proposal_dao = AlgorithmProposalDao()
algorithm_proposal_dao.set_config(
    config["couchdb"]["user"],
    config["couchdb"]["password"],
    config["couchdb"]["db_host"],
    config["couchdb"].get("algorithm_proposals_db", "algorithm_proposals"),
)
