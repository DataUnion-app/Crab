import unittest
from web3.auto import w3
from eth_account import Account
from eth_account.messages import defunct_hash_message, encode_defunct
from dao.users_dao import UsersDao
from dao.sessions_dao import SessionsDao
import json
import requests
from tests.helper import Helper


class TestUserAuthentication(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        user_dao = UsersDao()
        user_dao.set_config("admin", "admin", "127.0.0.1:5984", "users")
        user_dao.create_db()

        sessions_dao = SessionsDao()
        sessions_dao.set_config("admin", "admin", "127.0.0.1:5984", "sessions")
        sessions_dao.create_db()

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
        self.assertTrue(login_response_data.get('access_token') is not None)
        self.assertTrue(login_response_data.get('refresh_token') is not None)

    def test_user_logout(self):
        acct = Account.create('TEST')

        token = Helper.login(acct.address, acct.key)
        headers = {'Authorization': 'Bearer {0}'.format(token)}

        url = "http://localhost:8080/check"
        response = requests.request("GET", url, headers=headers, data=json.dumps({}))
        self.assertEqual(response.status_code, 200)

        # log out
        url = "http://localhost:8080/logout"
        logout_response = requests.request("POST", url, headers=headers, data=json.dumps({}))
        self.assertEqual(logout_response.status_code, 200)

        url = "http://localhost:8080/check"
        response = requests.request("GET", url, headers=headers, data=json.dumps({}))
        self.assertEqual(response.status_code, 401)

    def test_get_nonce(self):
        acct = Account.create('TEST')
        url = "http://localhost:8080/get-nonce?public_address={}".format(acct.address)
        response = requests.request("GET", url, headers={}, data=json.dumps({}))
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.text)
        self.assertEqual(data, {"status": "not found"})

    def test_get_nonce_of_registered_user(self):
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

        url = "http://localhost:8080/get-nonce?public_address={}".format(acct.address)
        response = requests.request("GET", url, headers={}, data=json.dumps({}))
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.text)
        self.assertEqual(data["status"], "exists")
        self.assertTrue(isinstance(data["nonce"], int))

    def test_refresh_token(self):
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
        refresh_token = login_response_data.get('refresh_token')

        self.assertTrue(refresh_token is not None)

        url = "http://localhost:8080/refresh"
        headers = {'Authorization': 'Bearer {0}'.format(refresh_token)}

        refresh_response = requests.request("POST", url, headers=headers, data=json.dumps({}))
        self.assertEqual(refresh_response.status_code, 200)
        refresh_response_data = json.loads(refresh_response.text)

        new_access_token = refresh_response_data.get("access_token")
        self.assertTrue(new_access_token is not None)

        headers = {'Authorization': 'Bearer {0}'.format(new_access_token)}

        url = "http://localhost:8080/check"
        response = requests.request("GET", url, headers=headers, data=json.dumps({}))
        self.assertEqual(response.status_code, 200)

    @classmethod
    def tearDownClass(cls):
        user_dao = UsersDao()
        user_dao.set_config("admin", "admin", "127.0.0.1:5984", "users")
        user_dao.delete_db()

        sessions_dao = SessionsDao()
        sessions_dao.set_config("admin", "admin", "127.0.0.1:5984", "sessions")
        sessions_dao.delete_db()


if __name__ == '__main__':
    unittest.main()
