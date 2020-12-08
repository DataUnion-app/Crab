import unittest
from web3.auto import w3
from eth_account import Account
from eth_account.messages import defunct_hash_message, encode_defunct
from dao.users_dao import UsersDao
import json
import requests


class TestUserAuthentication(unittest.TestCase):

    # self.user = "admin"
    # self.password = "admin"
    # self.host = ""
    # self.db = "users"

    def setUp(self):
        user_dao = UsersDao()
        user_dao.set_config("admin", "admin", "127.0.0.1:5984", "users")
        user_dao.create_db()

    def test_user_login(self):
        acct = Account.create('TEST')

        # Generate nonce
        url = "http://localhost:8080/register"
        payload = json.dumps({"public_address": acct.address})
        headers = {'Content-Type': 'application/json'}
        response = requests.request("POST", url, headers=headers, data=payload)
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.text)
        self.assertTrue(data["status"])
        self.assertTrue(data["nonce"] is not None)

        # Sign message
        nonce = data["nonce"]
        private_key = acct.key
        message = encode_defunct(text=str(nonce))
        signed_message = w3.eth.account.sign_message(message, private_key=private_key)
        signature = signed_message.signature

        # Generate jwt token

        url = "http://localhost:8080/login"
        payload = json.dumps({"public_address": acct.address, "signature": signature.hex()})
        headers = {'Content-Type': 'application/json'}

        login_response = requests.request("POST", url, headers=headers, data=payload)
        self.assertEqual(login_response.status_code, 200)
        login_response_data = json.loads(login_response.text)
        print(login_response_data)
        self.assertTrue(login_response_data.get('access_token') is not None)
        self.assertTrue(login_response_data.get('refresh_token') is not None)

    def tearDown(self):
        user_dao = UsersDao()
        user_dao.set_config("admin", "admin", "127.0.0.1:5984", "users")
        user_dao.delete_db()


if __name__ == '__main__':
    unittest.main()
