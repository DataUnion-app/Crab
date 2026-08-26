from flask import jsonify

from commands.base_command import BaseCommand
from dao.users_dao import UsersDao
from config import config


class GetUserCountCommand(BaseCommand):
    def __init__(self):
        super(GetUserCountCommand, self).__init__()
        user = config["couchdb"]["user"]
        password = config["couchdb"]["password"]
        db_host = config["couchdb"]["db_host"]
        user_db = config["couchdb"]["users_db"]
        self.user_dao = UsersDao()
        self.user_dao.set_config(user, password, db_host, user_db)

    def execute(self):
        result = self.user_dao.get_users_count()
        self.successful = True
        return {"count": result.get("count")}
