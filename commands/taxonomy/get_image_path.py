from commands.base_command import BaseCommand
from dao.taxonomy_dao import taxonomy_dao
import os


class GetImagePathCommand(BaseCommand):
    def __init__(self):
        super().__init__()

    def execute(self):
        document = taxonomy_dao.get_doc_by_id(self.input["image_id"])
        if document.get("error") == "not_found":
            self.messages.append("Document not found")
            self.successful = False
            return

        path = document["image_path"]
        if not os.path.isfile(path):
            self.messages.append("Image not found")
            self.successful = False

        self.successful = True
        return document["image_path"]
