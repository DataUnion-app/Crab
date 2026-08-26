import unittest
from web3.auto import w3
from eth_account import Account
from eth_account.messages import encode_defunct
import json
import requests
from helpers.login import Login
from tests.test_base import TestBase


class TestUserAuthentication(TestBase):
    def __init__(self, *args, **kwargs):
        super(TestUserAuthentication, self).__init__(*args, **kwargs)

    def test_user_login(self):
        acct = Account.create()

        # Generate nonce
        data = Login.register2(self.url, acct.address)

        # Sign message
        nonce = data["nonce"]
        private_key = acct.key
        message = encode_defunct(text=str(nonce))
        signed_message = w3.eth.account.sign_message(message, private_key=private_key)
        signature = signed_message.signature

        # Generate jwt token

        api_url = self.url + "/login"
        payload = json.dumps(
            {"public_address": acct.address, "signature": signature.hex()}
        )
        headers = {"Content-Type": "application/json"}

        login_response = requests.request(
            "POST", api_url, headers=headers, data=payload
        )
        self.assertEqual(login_response.status_code, 200)
        login_response_data = json.loads(login_response.text)
        self.assertTrue(login_response_data.get("access_token") is not None)
        self.assertTrue(login_response_data.get("refresh_token") is not None)

    def test_user_login_with_source(self):
        acct = Account.create()

        # Generate nonce
        data = Login.register2(self.url, acct.address)

        # Sign message
        nonce = data["nonce"]
        private_key = acct.key
        message = encode_defunct(text=str(nonce))
        signed_message = w3.eth.account.sign_message(message, private_key=private_key)
        signature = signed_message.signature

        # Generate jwt token

        api_url = self.url + "/login"

        # Generate jwt token with the source param
        payload = json.dumps(
            {
                "public_address": acct.address,
                "signature": signature.hex(),
                "source": "this is the testing"
            }
        )
        headers = {"Content-Type": "application/json"}

        login_response = requests.request(
            "POST", api_url, headers=headers, data=payload
        )
        self.assertEqual(login_response.status_code, 200)
        login_response_data = json.loads(login_response.text)
        self.assertTrue(login_response_data.get("access_token") is not None)
        self.assertTrue(login_response_data.get("refresh_token") is not None)

    def test_blocked_user_login(self):
        acct = Account.create()
        self.get_token_for_account(acct)

        user_dao = self.user_dao
        user_dao.block_access(acct.address)

        nonce = user_dao.get_nonce(acct.address)
        private_key = acct.key
        message = encode_defunct(text=str(nonce))
        signed_message = w3.eth.account.sign_message(message, private_key=private_key)
        signature = signed_message.signature

        api_url = self.url + "/login"
        payload = json.dumps(
            {"public_address": acct.address, "signature": signature.hex()}
        )
        headers = {"Content-Type": "application/json"}

        login_response = requests.request(
            "POST", api_url, headers=headers, data=payload
        )
        self.assertEqual(login_response.status_code, 400)
        login_response_data = json.loads(login_response.text)
        self.assertEqual(login_response_data.get("status"), "failed")
        self.assertEqual("Access is blocked", login_response_data.get("message"))

        user_dao.unblock_access(acct.address)

        nonce = user_dao.get_nonce(acct.address)["nonce"]
        private_key = acct.key
        message = encode_defunct(text=str(nonce))
        signed_message2 = w3.eth.account.sign_message(message, private_key=private_key)
        signature2 = signed_message2.signature

        api_url = self.url + "/login"
        payload2 = json.dumps(
            {"public_address": acct.address, "signature": signature2.hex()}
        )
        headers2 = {"Content-Type": "application/json"}

        login_response2 = requests.request(
            "POST", api_url, headers=headers2, data=payload2
        )
        self.assertEqual(200, login_response2.status_code)
        login_response_data2 = json.loads(login_response2.text)
        self.assertIsNotNone(login_response_data2.get("access_token"))
        self.assertIsNotNone(login_response_data2.get("refresh_token"))

    def test_user_logout(self):
        acct = Account.create()

        token = self.get_token_for_account(acct)
        headers = {"Authorization": "Bearer {0}".format(token)}

        api_url = self.url + "/check"
        response = requests.request(
            "GET", api_url, headers=headers, data=json.dumps({})
        )
        self.assertEqual(response.status_code, 200)

        # log out
        api_url = self.url + "/logout"
        logout_response = requests.request(
            "POST", api_url, headers=headers, data=json.dumps({})
        )
        self.assertEqual(logout_response.status_code, 200)

        api_url = self.url + "/check"
        response = requests.request(
            "GET", api_url, headers=headers, data=json.dumps({})
        )
        self.assertEqual(response.status_code, 401)

    def test_get_nonce(self):
        acct = Account.create()
        api_url = self.url + "/get-nonce?public_address={}".format(acct.address)
        response = requests.request("GET", api_url, headers={}, data=json.dumps({}))
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.text)
        self.assertEqual(data, {"status": "not found"})

    def test_get_nonce_of_registered_user(self):
        acct = Account.create()

        # Generate nonce
        api_url = self.url + "/register"
        payload = json.dumps({"public_address": acct.address})
        headers = {"Content-Type": "application/json"}
        response = requests.request("POST", api_url, headers=headers, data=payload)
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.text)
        self.assertTrue(data["status"])
        self.assertTrue(data["nonce"] is not None)

        api_url = self.url + "/get-nonce?public_address={}".format(acct.address)
        response = requests.request("GET", api_url, headers={}, data=json.dumps({}))
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.text)
        self.assertEqual(data["status"], "exists")
        self.assertTrue(isinstance(data["nonce"], int))

    def test_refresh_token(self):
        acct = Account.create()

        # Generate nonce
        data = Login.register2(self.url, acct.address)

        # Sign message
        nonce = data["nonce"]
        private_key = acct.key
        message = encode_defunct(text=str(nonce))
        signed_message = w3.eth.account.sign_message(message, private_key=private_key)
        signature = signed_message.signature

        # Generate jwt token

        api_url = self.url + "/login"
        payload = json.dumps(
            {"public_address": acct.address, "signature": signature.hex()}
        )
        headers = {"Content-Type": "application/json"}

        login_response = requests.request(
            "POST", api_url, headers=headers, data=payload
        )
        self.assertEqual(login_response.status_code, 200)
        login_response_data = json.loads(login_response.text)
        refresh_token = login_response_data.get("refresh_token")

        self.assertTrue(refresh_token is not None)

        api_url = self.url + "/refresh"
        headers = {"Authorization": "Bearer {0}".format(refresh_token)}

        refresh_response = requests.request(
            "POST", api_url, headers=headers, data=json.dumps({})
        )
        self.assertEqual(refresh_response.status_code, 200)
        refresh_response_data = json.loads(refresh_response.text)

        new_access_token = refresh_response_data.get("access_token")
        self.assertTrue(new_access_token is not None)

        headers = {"Authorization": "Bearer {0}".format(new_access_token)}

        api_url = self.url + "/check"
        response = requests.request(
            "GET", api_url, headers=headers, data=json.dumps({})
        )
        self.assertEqual(response.status_code, 200)

    def test_revoke_refresh_token(self):
        acct = Account.create()

        # Generate nonce
        data = Login.register2(self.url, acct.address)

        # Sign message
        nonce = data["nonce"]
        private_key = acct.key
        message = encode_defunct(text=str(nonce))
        signed_message = w3.eth.account.sign_message(message, private_key=private_key)
        signature = signed_message.signature

        # Generate jwt token

        api_url = self.url + "/login"
        payload = json.dumps(
            {"public_address": acct.address, "signature": signature.hex()}
        )
        headers = {"Content-Type": "application/json"}

        login_response = requests.request(
            "POST", api_url, headers=headers, data=payload
        )
        self.assertEqual(login_response.status_code, 200)
        login_response_data = json.loads(login_response.text)
        refresh_token = login_response_data.get("refresh_token")

        self.assertTrue(refresh_token is not None)

        headers = {"Authorization": "Bearer {0}".format(refresh_token)}

        api_url = self.url + "/revoke-refresh-token"
        response = requests.request(
            "POST", api_url, headers=headers, data=json.dumps({})
        )
        self.assertEqual(response.status_code, 200)
        revoke_data = json.loads(response.text)
        self.assertEqual(revoke_data, {"message": "Refresh token has been revoked"})

        api_url = self.url + "/refresh"
        headers = {"Authorization": "Bearer {0}".format(refresh_token)}

        refresh_response = requests.request(
            "POST", api_url, headers=headers, data=json.dumps({})
        )
        self.assertEqual(refresh_response.status_code, 401)
        refresh_response_data = json.loads(refresh_response.text)
        self.assertEqual(refresh_response_data, {"msg": "Token has been revoked"})

    def test_referral_link(self):
        token = self.get_token()

        api_url = self.url + "/api/v1/user/referral-id"
        headers = {"Authorization": "Bearer {0}".format(token)}

        response = requests.request(
            "GET", api_url, headers=headers, data=json.dumps({})
        )
        referral_id = response.json()["result"]["referral_id"]
        self.assertEqual(response.status_code, 200)

        acct = Account.create()

        # Generate nonce
        api_url = self.url + "/register"
        payload = json.dumps({"public_address": acct.address, "referral_id": referral_id})
        headers = {"Content-Type": "application/json"}
        response = requests.request("POST", api_url, headers=headers, data=payload)
        self.assertEqual(response.status_code, 200)

        acct = Account.create()

        # Generate nonce
        api_url = self.url + "/register"
        payload = json.dumps({"public_address": acct.address})
        headers = {"Content-Type": "application/json"}
        response = requests.request("POST", api_url, headers=headers, data=payload)
        self.assertEqual(response.status_code, 200)


if __name__ == "__main__":
    unittest.main()
