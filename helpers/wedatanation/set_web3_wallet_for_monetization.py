import json
import getpass

import requests
from eth_account.messages import encode_defunct
from web3.auto import w3
import sys
import argparse
import logging
from config import config
from helpers.input_validators.address import ValidateAddress
from helpers.login import get_token
from models.metadata.metadata_models import Network, Source

logging.basicConfig(stream=sys.stdout, level=logging.INFO)

parser = argparse.ArgumentParser()
parser.add_argument("--address", help="Wallet address", required=True, action=ValidateAddress)
parser.add_argument('--source', type=str, required=False, default=Source.default)
parser.add_argument('--network', type=str, required=False, default=Network.default)

if __name__ == "__main__":
    args = parser.parse_args()
    public_address = args.address
    source = args.source
    network = args.network

    acct_key = getpass.getpass(prompt="Private key:")

    token = get_token(public_address, acct_key, source)['access_token']

    url = "http://localhost:{}".format(config["application"]["port"])
    headers = {"Authorization": "Bearer {0}".format(token)}

    # Get nonce
    nonce_api_url = url + f"/api/v1/metadata/web3-wallet/nonce?wallet_address={public_address}"
    response = requests.request("GET", nonce_api_url, headers=headers, data={})

    assert response.status_code == 200

    nonce = response.json()["nonce"]
    message = encode_defunct(text=nonce)
    signed_message = w3.eth.account.sign_message(message, private_key=acct_key)
    signature = signed_message.signature

    payload = json.dumps({"wallet_address": public_address, "signature": signature.hex(), "network": network})
    api_url = url + "/api/v1/metadata/web3-wallet"
    response = requests.request("POST", api_url, headers=headers, data=payload)

    logging.info("response code [%s]", response.status_code)
    logging.info("Result: [%s]", response.text)
