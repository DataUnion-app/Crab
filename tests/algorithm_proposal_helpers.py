from copy import deepcopy


SCIENTIST = "0x" + "1" * 40
OTHER = "0x" + "2" * 40
ADMIN = "0x" + "a" * 40


def revision_payload(**changes):
    payload = {
        "title": "Resting R-R cohort summary",
        "scientific_purpose": "Estimate aggregate resting heart-rate variability safely.",
        "source_url": "https://github.com/example/research-algorithm",
        "paper_url": "https://doi.org/10.1000/example",
        "input_schema_version": "brainstem.private-rr-cohort/v1",
        "result_schema_version": "brainstem.c2d-result/v1",
    }
    payload.update(changes)
    return payload


class InMemoryProposalDao:
    def __init__(self):
        self.documents = {}

    def create(self, document):
        self.documents[document["proposal_id"]] = deepcopy(document)

    def get(self, proposal_id):
        return deepcopy(self.documents[proposal_id])

    def mutate(self, proposal_id, mutator):
        updated = mutator(deepcopy(self.documents[proposal_id]))
        self.documents[proposal_id] = deepcopy(updated)
        return deepcopy(updated)

    def list_owned(self, wallet, page, per_page):
        rows = [
            self._summary(document)
            for document in self._ordered()
            if document["submitter_wallet"] == wallet
        ]
        return self._page(rows, page, per_page)

    def list_queue(self, page, per_page, status=None):
        rows = [
            self._summary(document)
            for document in self._ordered()
            if status is None or document["status"] == status
        ]
        return self._page(rows, page, per_page)

    def _ordered(self):
        return sorted(
            self.documents.values(), key=lambda item: item["updated_at"], reverse=True
        )

    @staticmethod
    def _summary(document):
        return {
            key: deepcopy(document[key])
            for key in (
                "proposal_id",
                "submitter_wallet",
                "title",
                "status",
                "current_revision_id",
                "current_revision_number",
                "created_at",
                "updated_at",
            )
        }

    @staticmethod
    def _page(rows, page, per_page):
        start = page * per_page
        selected = rows[start : start + per_page]
        return selected, len(rows) > start + per_page
