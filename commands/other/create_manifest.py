from commands.base_command import BaseCommand
from dao.base_dao import DBResultError
from dao.others_dao import others_db


class CreateManifest(BaseCommand):
    def __init__(self, public_address: str, doc_id: str, data: dict = None):
        super(CreateManifest, self).__init__(public_address)
        self.doc_id = doc_id
        self.data = data

    def execute(self):
        document = {"type": "public_document", "data": self.data}

        try:
            others_db.save(self.doc_id, document)
            self.successful = True
            return {"status": "successful"}
        except DBResultError as e:
            self.successful = False
            self.messages.append(e.message)
            return
