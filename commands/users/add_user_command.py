from flask import jsonify

from commands.base_command import BaseCommand
from dao.users_dao import user_dao


class AddUserCommand(BaseCommand):
    def __init__(self, public_address: str, ):
        super(AddUserCommand, self).__init__(public_address)

    def execute(self):
        self.successful = False
        if not self.validate_input():
            return {"status": "failed"}

        result = user_dao.get_nonce(self.public_address)
        if result["status"] == "exists":
            return jsonify({"status": "failed", "message": "already exists"}), 400

        nonce, referrer_public_address = user_dao.register_and_get_nonce_if_not_exists(self.public_address)
        self.successful = True
        return {"status": "success", "nonce": nonce}

    def validate_input(self):
        if not isinstance(self.public_address, str):
            return False
        return True
