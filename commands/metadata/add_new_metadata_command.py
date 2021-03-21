import unicodedata

from dao.image_metadata_dao import ImageMetadataDao
from commands.base_command import BaseCommand
from config import config


class AddNewMetadataCommand(BaseCommand):

    def __init__(self):
        user = config['couchdb']['user']
        password = config['couchdb']['password']
        db_host = config['couchdb']['db_host']
        metadata_db = config['couchdb']['metadata_db']
        self.imageMetadataDao = ImageMetadataDao()
        self.imageMetadataDao.set_config(user, password, db_host, metadata_db)

    def execute(self):
        self.clean_input()
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

    @property
    def is_valid(self):
        pass
