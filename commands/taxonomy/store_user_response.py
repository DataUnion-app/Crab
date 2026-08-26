from commands.base_command import BaseCommand
from dao.taxonomy_dao import taxonomy_dao
from datetime import datetime

from models.taxonomy.TaxonomyTypes import TaxonomyTypes


class StoreUserResponse(BaseCommand):
    def __init__(self):
        super().__init__()

    def execute(self):
        if not self.validate_input():
            self.successful = False
            return

        document = taxonomy_dao.get_doc_by_id(self.input.get("image_id"))
        if document.get("error") == "not_found":
            self.messages.append("Document not found")
            self.successful = False
            return
        if document["type"] != TaxonomyTypes.CROP.name:
            self.messages.append(
                "Cannot add data to document of type [{0}]".format(document["type"])
            )
            self.successful = False
            return
        user_response = {
            "public_address": self.input["public_address"],
            "created_at": datetime.timestamp(datetime.now()),
            "response": self.input.get("response"),
        }

        if not document.get("verified"):
            document["verified"] = [user_response]
        else:
            found = False
            for index, responses in enumerate(document["verified"]):
                if responses["public_address"] == self.input["public_address"]:
                    document["verified"][index] = user_response
                    found = True
                    break

            if not found:
                document["verified"].append(user_response)

        document["updated_at"] = datetime.timestamp(datetime.now())
        taxonomy_dao.update_doc(document["_id"], document)

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

        if not isinstance(self.input.get("response"), str) or (
            self.input["response"] not in ["YES", "NO"]
        ):
            self.messages.append("Invalid 'response'")
            return False
        return True
