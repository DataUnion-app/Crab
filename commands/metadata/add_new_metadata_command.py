import unicodedata

from dao.image_metadata_dao import ImageMetadataDao
from commands.base_command import BaseCommand
from config import config


class AddNewMetadataCommand(BaseCommand):
    MAX_DESCRIPTION_LENGTH = 2000
    MAX_TAG_LENGTH = 200

    def __init__(self):
        super().__init__()
        user = config['couchdb']['user']
        password = config['couchdb']['password']
        db_host = config['couchdb']['db_host']
        metadata_db = config['couchdb']['metadata_db']
        self.imageMetadataDao = ImageMetadataDao()
        self.imageMetadataDao.set_config(user, password, db_host, metadata_db)
        self.max_tag_length = 200

    def execute(self):
        self.clean_input()
        is_valid = self.validate_input()

        if not is_valid:
            self.successful = False
            return {"status": "failed"}

        result = self.imageMetadataDao.add_metadata_for_image(self.input["public_address"], self.input["photo_id"],
                                                              self.input["tags"],
                                                              self.input.get("description", None))

        if result.get('ok') is True:
            self.imageMetadataDao.move_to_verifiable_if_possible(self.input["photo_id"])
            self.successful = True
            return {"status": "success"}

        self.successful = False
        return {"status": "failed"}

    def clean_input(self):
        self.input['tags'] = list(map(str.strip, self.input.get("tags")))
        self.input['tags'] = list(map(AddNewMetadataCommand.remove_control_characters, self.input.get("tags")))

    @staticmethod
    def remove_control_characters(tag):
        return "".join(ch for ch in tag if unicodedata.category(ch)[0] != "C")

    def validate_input(self):
        if self.input.get("description") is not None:
            if len(self.input.get("description")) > AddNewMetadataCommand.MAX_DESCRIPTION_LENGTH:
                self.messages.append(
                    "Length of description exceeds limit of [{0}] characters.".format(
                        AddNewMetadataCommand.MAX_DESCRIPTION_LENGTH))
                return False

        all_tags_in_limit = all([len(tag) <= self.max_tag_length for tag in self.input.get("tags")])

        if not all_tags_in_limit:
            self.messages.append(
                "Length of tag(s) exceeds limit of [{0}] characters.".format(AddNewMetadataCommand.MAX_TAG_LENGTH))
            return False
        return True

    @property
    def is_valid(self):
        pass
