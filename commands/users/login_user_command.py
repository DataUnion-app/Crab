from eth_account.messages import encode_defunct
from web3.auto import w3

from commands.base_command import BaseCommand
from dao.users_dao import user_dao


class LoginUserCommand(BaseCommand):
    def __init__(self):
        super(LoginUserCommand, self).__init__()
        self.user_dao = user_dao

    def execute(self):
        # TODO
        # nonce = user_dao.get_nonce(self.input['public_address'])['nonce']
        # private_key = self.input['private_key']
        # message = encode_defunct(text=str(nonce))
        # signed_message = w3.eth.account.sign_message(message, private_key=private_key)
        # signature = signed_message.signature

        pass
