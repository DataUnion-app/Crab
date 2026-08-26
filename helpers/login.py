import argparse
import json
import requests
import getpass
import sys
from web3.auto import w3
from eth_account.messages import encode_defunct
from config import config
from models.metadata.metadata_models import Source
from routes.authentication_routes import user_dao
import logging

from helpers.input_validators.address import ValidateAddress

logging.basicConfig(stream=sys.stdout, level=logging.INFO)

parser = argparse.ArgumentParser()
parser.add_argument("--address", help="Wallet address", required=True, action=ValidateAddress)
parser.add_argument('--source', type=str, required=False, default=Source.default)


class Login:
    def __init__(self, *args, **kwargs):
        self.url = "http://localhost:{}".format(config["application"]["port"])

    def register_and_login(self, address, key, source: Source = Source.default):
        return Login.register_and_login2(self.url, address, key, source)['access_token']

    @staticmethod
    def register_and_login2(url, address, key, source: Source = Source.default):
        # Generate nonce
        Login.register2(url, address)
        return Login.login2(url, address, key, source)

    @staticmethod
    def login2(url, address, key, source: Source = Source.default):
        response = user_dao.get_nonce(address)

        if "exists" != response["status"]:
            logging.error("User [%s] found", address)
            sys.exit(-1)

        nonce = response["nonce"]
        private_key = key
        message = encode_defunct(text=str(nonce))
        signed_message = w3.eth.account.sign_message(message, private_key=private_key)
        signature = signed_message.signature

        # Generate jwt token
        api_url = url + "/login"
        params = {"public_address": address, "signature": signature.hex(), "source": source}

        payload = json.dumps(params)
        headers = {"Content-Type": "application/json"}

        login_response = requests.request(
            "POST", api_url, headers=headers, data=payload
        )
        login_response_data = json.loads(login_response.text)
        return login_response_data

    @staticmethod
    def login3(url, address, key, source: Source = Source.default):
        response = user_dao.get_nonce(address)

        if "exists" != response["status"]:
            logging.error("User [%s] found", address)
            sys.exit(-1)

        nonce = response["nonce"]
        private_key = key
        message = encode_defunct(text=str(nonce))
        signed_message = w3.eth.account.sign_message(message, private_key=private_key)
        signature = signed_message.signature

        # Generate jwt token
        api_url = url + "/login"
        payload = json.dumps({"public_address": address, "signature": signature.hex(), "source": source})
        headers = {"Content-Type": "application/json"}

        login_response = requests.request(
            "POST", api_url, headers=headers, data=payload
        )
        login_response_data = json.loads(login_response.text)
        return login_response_data

    def login(self, address, key, source: Source = Source.default):
        nonce_res = user_dao.get_nonce(address)
        nonce = nonce_res.get("nonce")
        if nonce:
            private_key = key
            message = encode_defunct(text=str(nonce))
            signed_message = w3.eth.account.sign_message(
                message, private_key=private_key
            )
            signature = signed_message.signature

            # Generate jwt token
            api_url = self.url + "/login"
            payload = json.dumps(
                {"public_address": address, "signature": signature.hex(), "source": source}
            )
            headers = {"Content-Type": "application/json"}

            login_response = requests.request(
                "POST", api_url, headers=headers, data=payload
            )
            login_response_data = json.loads(login_response.text)
            return login_response_data
        else:
            print("Nonce not found")

    def user_exists(self, address):
        nonce_res = user_dao.get_nonce(address)
        nonce = nonce_res.get("nonce")
        if nonce:
            return True, nonce
        return False, None

    def register(self, address):
        # Generate nonce
        api_url = self.url + "/register"
        payload = json.dumps({"public_address": address})
        headers = {"Content-Type": "application/json"}
        response = requests.request("POST", api_url, headers=headers, data=payload)
        data = json.loads(response.text)
        return data

    @staticmethod
    def register2(url, address):
        api_url = url + "/register"
        payload = json.dumps({"public_address": address})
        headers = {"Content-Type": "application/json"}
        response = requests.request("POST", api_url, headers=headers, data=payload)
        data = json.loads(response.text)
        return data


def get_token(public_address: str, acct_key: str, source: Source):
    login = Login()
    exists, nonce = login.user_exists(public_address)

    if exists:
        token = login.login(public_address, acct_key, source)
    else:
        token = login.register_and_login(public_address, acct_key, source)
    return token


if __name__ == "__main__":

    args = parser.parse_args()
    public_address = args.address
    source = args.source

    acct_key = getpass.getpass(prompt="Private key:")
    login = Login()
    exists, nonce = login.user_exists(public_address)

    if exists:
        token = login.login(public_address, acct_key, source)
    else:
        token = login.register_and_login(public_address, acct_key, source)

    print("token:", token)
