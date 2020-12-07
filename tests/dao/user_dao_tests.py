import unittest
from web3.auto import w3
from eth_account import Account
from eth_account.messages import defunct_hash_message, encode_defunct
from dao.users_dao import UsersDao


class TestUserDao(unittest.TestCase):

    def test_get_nonce(self):
        user_dao = UsersDao()
        user_dao.set_config("admin", "admin", "127.0.0.1:5984", "users")
        acct = Account.create('TEST')
        result = user_dao.get_nonce_if_not_exists(acct.address)
        print(result)
        self.assertTrue(result is not None)

    def test_verify_signature(self):
        user_dao = UsersDao()
        user_dao.set_config("admin", "admin", "127.0.0.1:5984", "users")
        acct = Account.create('TEST')
        nonce = user_dao.get_nonce_if_not_exists(acct.address)
        private_key = acct.key
        message = encode_defunct(text=str(nonce))

        signed_message = w3.eth.account.sign_message(message, private_key=private_key)
        print("signed_message", signed_message)
        result = user_dao.verify_signature(acct.address, signed_message.signature)
        self.assertTrue(result)


if __name__ == '__main__':
    unittest.main()
