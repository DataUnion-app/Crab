import unicodedata

from dao.image_metadata_dao import ImageMetadataDao
from dao.static_data_dao import StaticDataDao, WordTypes
from commands.base_command import BaseCommand
from config import config


class AddNewMetadataCommand(BaseCommand):

    def __init__(self):
        super().__init__()
        user = config['couchdb']['user']
        password = config['couchdb']['password']
        db_host = config['couchdb']['db_host']
        metadata_db = config['couchdb']['metadata_db']
        self.image_metadata_dao = ImageMetadataDao()
        self.image_metadata_dao.set_config(user, password, db_host, metadata_db)
        self.staticdata_dao = StaticDataDao()
        self.staticdata_dao.set_config(user, password, db_host, config['couchdb']['static_data_db'])

    def execute(self):
        self.clean_input()

        banned_words = self.staticdata_dao.get_words_by_type(WordTypes.BANNED_WORDS.name)

        tags_lower_case = map(lambda x: x.lower(), self.input['tags'])

        banned_words_in_input = list(set(tags_lower_case) & set(banned_words))
        if len(banned_words_in_input) > 0:
            self.messages.append("Tags contains banned words {}".format(banned_words_in_input))
            self.successful = False
            return {"status": "failed"}

        result = self.image_metadata_dao.add_metadata_for_image(self.input["public_address"], self.input["photo_id"],
                                                                self.input["tags"],
                                                                self.input.get("description", None))

        if result.get('ok') is True:
            self.image_metadata_dao.move_to_verifiable_if_possible(self.input["photo_id"])
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
