from commands.base_command import BaseCommand
from dao.users_dao import user_dao


class GetNonceCommand(BaseCommand):

    def __init__(self, public_address: str):
        super(GetNonceCommand, self).__init__()
        self.public_address = public_address

    def execute(self):
        nonce = user_dao.get_nonce(self.public_address).get("nonce")
        if nonce is None:
            self.successful = True
            return nonce
