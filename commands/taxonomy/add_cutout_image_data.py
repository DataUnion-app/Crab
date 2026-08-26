from commands.base_command import BaseCommand
from dao.taxonomy_dao import taxonomy_dao
from datetime import datetime


class AddCutoutImageData(BaseCommand):
    def __init__(self):
        super().__init__()

    def execute(self):

        parent_document = taxonomy_dao.get_doc_by_id(self.input["parent_image_id"])
        if parent_document.get("error") == "not_found":
            self.messages.append("Parent Document not found")
            self.successful = False
            return

        cutout_document = {}
        cutout_document["_id"] = self.input["image_id"]
        cutout_document["type"] = "cutout"
        cutout_document["parent_image_id"] = self.input["parent_image_id"]
        cutout_document["image_id"] = self.input["image_id"]
        cutout_document["uploaded_by"] = self.input["public_address"]
        cutout_document["image_path"] = self.input["image_path"]
        cutout_document["created_at"] = datetime.timestamp(datetime.now())
        cutout_document["updated_at"] = datetime.timestamp(datetime.now())
        taxonomy_dao.save(cutout_document["_id"], cutout_document)

        parent_document["cutout_images"].append(self.input["image_id"])
        taxonomy_dao.update_doc(parent_document["_id"], parent_document)
        self.successful = True
        return

    def validate_input(self):
        if not self.input:
            self.messages.append("Empty input")
            return False
        if not isinstance(self.input.get("public_address"), str):
            self.messages.append("Empty public_address")
            return False

        if not isinstance(self.input.get("image_id"), str):
            self.messages.append("Empty image_id")
            return False

        if not isinstance(self.input.get("image_path"), str):
            self.messages.append("Empty image_path")
            return False

        if not isinstance(self.input.get("parent_image_id"), str):
            self.messages.append("Empty parent_image_id")
            return False

        return True
