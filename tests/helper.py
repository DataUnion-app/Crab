import json
import requests
from web3.auto import w3
from eth_account.messages import defunct_hash_message, encode_defunct


class Helper:

    @staticmethod
    def login(address, key):
        # Generate nonce
        url = "http://localhost:8080/register"
        payload = json.dumps({"public_address": address})
        headers = {'Content-Type': 'application/json'}
        response = requests.request("POST", url, headers=headers, data=payload)
        data = json.loads(response.text)

        # Sign message
        nonce = data["nonce"]
        private_key = key
        message = encode_defunct(text=str(nonce))
        signed_message = w3.eth.account.sign_message(message, private_key=private_key)
        signature = signed_message.signature

        # Generate jwt token
        url = "http://localhost:8080/login"
        payload = json.dumps({"public_address": address, "signature": signature.hex()})
        headers = {'Content-Type': 'application/json'}

        login_response = requests.request("POST", url, headers=headers, data=payload)
        login_response_data = json.loads(login_response.text)
        return login_response_data.get('access_token')

    @staticmethod
    def register(address):
        # Generate nonce
        url = "http://localhost:8080/register"
        payload = json.dumps({"public_address": address})
        headers = {'Content-Type': 'application/json'}
        response = requests.request("POST", url, headers=headers, data=payload)
        data = json.loads(response.text)
        return data