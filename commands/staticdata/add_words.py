from commands.base_command import BaseCommand
from config import config
from dao.static_data_dao import StaticDataDao, WordTypes


class AddWordsCommand(BaseCommand):
    def __init__(self):
        super().__init__()

        user = config["couchdb"]["user"]
        password = config["couchdb"]["password"]
        db_host = config["couchdb"]["db_host"]
        metadata_db = config["couchdb"]["static_data_db"]
        self.staticdata_dao = StaticDataDao()
        self.staticdata_dao.set_config(user, password, db_host, metadata_db)

    def execute(self):
        if not self.validate_input():
            self.successful = False
            return
        self.staticdata_dao.add_words(self.input["words"], self.input.get("type"))
        self.successful = True

    def validate_input(self):
        if not self.input:
            self.messages.append("Empty input.")
            return False
        if not isinstance(self.input.get("words"), list):
            self.messages.append("'words' parameter is not a list.")
            return False
        if not self.input.get("type") in WordTypes.__members__:
            self.messages.append("'words' parameter is not a list.")
            return False

        return True
