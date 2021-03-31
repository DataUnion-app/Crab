from flask import jsonify

from commands.base_command import BaseCommand
from dao.users_dao import UsersDao
from config import config


class AddUserCommand(BaseCommand):
    def __init__(self):
        super(AddUserCommand, self).__init__()
        user = config['couchdb']['user']
        password = config['couchdb']['password']
        db_host = config['couchdb']['db_host']
        user_db = config['couchdb']['users_db']
        self.user_dao = UsersDao()
        self.user_dao.set_config(user, password, db_host, user_db)

    def execute(self):
        if not self.validate_input():
            self.successful = False
            return {"status": 'failed'}

        result = self.user_dao.get_nonce(self.input['public_address'])
        if result["status"] == "exists":
            return jsonify({"status": "failed", "message": "already exists"}), 400

        nonce = self.user_dao.get_nonce_if_not_exists(self.input['public_address'])
        self.successful = True
        return {"status": "success", "nonce": nonce}

    def validate_input(self):
        if not self.input:
            self.messages.append("Empty Input")
            return False
        if not isinstance(self.input['public_address'], str):
            return False
        return True
