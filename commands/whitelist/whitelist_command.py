from commands.base_command import BaseCommand
from dao.whitelist_dao import WhitelistDao
from config import config
from helpers.permission.whitelist import WHITELIST


class WhitelistCommand(BaseCommand):
    def __init__(self):
        super(WhitelistCommand, self).__init__()
        user = config["couchdb"]["user"]
        password = config["couchdb"]["password"]
        db_host = config["couchdb"]["db_host"]
        user_db = config["couchdb"]["permission_db"]
        self.whitelist_dao = WhitelistDao()
        self.whitelist_dao.set_config(user, password, db_host, user_db)

    def execute(self):
        pass

    def prepare_whitelist(self, whitelists=WHITELIST):
        result = self.whitelist_dao.save_whitelists(whitelists)
        print("The whitelist document in the permission database has been updated successfully. \n")
        self.successful = True
        return result

    def get_latest_whitelist(self):
        return self.whitelist_dao.get_whitelists()
