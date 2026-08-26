import logging

from flask_jwt_extended import create_refresh_token, create_access_token

from commands.base_command import BaseCommand
from dao.base_dao import DBResultError
from dao.users_dao import user_dao
from models.User import USER_ROLE


class LoginUserCommand(BaseCommand):
    def __init__(self, public_address: str, signature: str):
        super(LoginUserCommand, self).__init__()
        self.public_address = public_address
        self.signature = signature

    def execute(self):
        try:
            user = user_dao.get_by_public_address(public_address=self.public_address)["result"]
            if not user:
                self.messages.append("User not found")
                return
            user = user[0]
            if user["is_access_blocked"]:
                self.messages.append("Access is blocked")
                return
            logging.info("Verifying signature for [{}]".format(self.public_address))

            result = user_dao.verify_signature(self.public_address, self.signature)
            if not result:
                self.messages.append("Signature invalid")
                return

            is_admin = True if USER_ROLE['ADMIN'] in user.get("claims", []) else False
            access_token = create_access_token(identity=self.public_address,
                                               user_claims={"is_admin": is_admin})
            refresh_token = create_refresh_token(identity=self.public_address,
                                                 user_claims={"is_admin": is_admin})
            user_dao.update_nonce(self.public_address)
            self.successful = True
            return {
                "status": "success",
                "message": "Public address [{}] registered".format(self.public_address),
                "access_token": access_token,
                "refresh_token": refresh_token,
            }

        except DBResultError as e:
            logging.exception(e, exc_info=True)
            self.successful = False
        except Exception as e:
            self.successful = False
            logging.exception(e, exc_info=True)
            return {"message": "Something went wrong"}, 500
