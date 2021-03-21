from commands.base_command import BaseCommand
from config import config
from dao.static_data_dao import StaticDataDao


class AddBannedWordsCommand(BaseCommand):

    def __init__(self):
        super().__init__()

        user = config['couchdb']['user']
        password = config['couchdb']['password']
        db_host = config['couchdb']['db_host']
        metadata_db = config['couchdb']['static_data_db']
        self.staticdata_dao = StaticDataDao()
        self.staticdata_dao.set_config(user, password, db_host, metadata_db)

    def execute(self):
        self.staticdata_dao.add_banned_words(self.input['words'])
        self.successful = True
