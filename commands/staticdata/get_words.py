from commands.base_command import BaseCommand
from config import config
from dao.static_data_dao import StaticDataDao, WordTypes


class GetWordsByTypeCommand(BaseCommand):
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
        result = self.staticdata_dao.get_words_by_type(self.input["type"])
        self.successful = True
        return result

    def validate_input(self):
        if not self.input:
            self.messages.append("Empty input.")
            return False
        if not self.input.get("type") in WordTypes.__members__:
            self.messages.append("'type' parameter is not valid.")
            return False
        return True
