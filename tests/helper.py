import json
import requests
from web3.auto import w3
from eth_account.messages import defunct_hash_message, encode_defunct
import os


class Helper:
    URL = "http://localhost:8080"

    @staticmethod
    def login(address, key):
        # Generate nonce
        api_url = Helper.URL + "/register"
        payload = json.dumps({"public_address": address})
        headers = {'Content-Type': 'application/json'}
        response = requests.request("POST", api_url, headers=headers, data=payload)
        data = json.loads(response.text)

        # Sign message
        nonce = data["nonce"]
        private_key = key
        message = encode_defunct(text=str(nonce))
        signed_message = w3.eth.account.sign_message(message, private_key=private_key)
        signature = signed_message.signature

        # Generate jwt token
        api_url = Helper.URL + "/login"
        payload = json.dumps({"public_address": address, "signature": signature.hex()})
        headers = {'Content-Type': 'application/json'}

        login_response = requests.request("POST", api_url, headers=headers, data=payload)
        login_response_data = json.loads(login_response.text)
        return login_response_data.get('access_token')

    @staticmethod
    def register(address):
        # Generate nonce
        api_url = Helper.URL + "/register"
        payload = json.dumps({"public_address": address})
        headers = {'Content-Type': 'application/json'}
        response = requests.request("POST", api_url, headers=headers, data=payload)
        data = json.loads(response.text)
        return data

    @staticmethod
    def get_project_root():
        return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


