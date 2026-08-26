from commands.base_command import BaseCommand
from dao.others_dao import others_db


class GetPublicDocument(BaseCommand):
    def __init__(self, doc_id: str):
        super(GetPublicDocument, self).__init__()
        self.doc_id = doc_id

    def execute(self):
        if self.doc_id is not None:
            query = {
                "selector": {
                    "_id": self.doc_id,
                    "type": "public_document"
                },
                "limit": 1,
                "fields": ["data"]
            }
            result = others_db.query_data(query)
            self.successful = True
            return result
