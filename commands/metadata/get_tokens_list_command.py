import json
import requests
from config import config
from commands.base_command import BaseCommand
from web3 import Web3

class GetTokensListCommand(BaseCommand):
    def __init__(self, wallet_address: str):
        super().__init__()
        self.wallet_address = wallet_address

    def execute(self):
        payload = {
            "id": 1,
            "jsonrpc": "2.0",
            "method": "alchemy_getTokenBalances",
            "params": [self.wallet_address]
        }
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json"
        }

        response = requests.post(config['rewards']['network_url'], json=payload, headers=headers)

        if response.status_code != 200:
            self.successful = False
            self.messages.append(response.text)
            return

        token_balances = json.loads(response.text)['result']['tokenBalances']

        tokens = []
        for token in token_balances:
            if Web3.fromWei(int(token['tokenBalance'], 16), 'ether') > 0:
                tokens.append(token['contractAddress'])

        return tokens


