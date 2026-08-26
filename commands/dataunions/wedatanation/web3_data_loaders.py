from datetime import datetime
import json
from typing import List, Optional
from config import config
from commands.base_command import BaseCommand
from dao.metadata_dao import image_metadata_dao
from models.metadata.metadata_models import Network
import requests


class SaveTokenBalancesByUser(BaseCommand):
    def __init__(self, public_address: str, wallet_address: str, network: Network, tokens: Optional[List[str]] = None,
                 update_database: bool = True):
        super(SaveTokenBalancesByUser, self).__init__(public_address)
        self.network = network
        self.metadata_dao = image_metadata_dao
        self.update_database = update_database
        self.wallet_address = wallet_address
        if tokens is None:
            self.tokens = "DEFAULT_TOKENS"
        else:
            self.tokens = tokens

    def execute(self):

        if self.network not in [Network.eth_mainnet, Network.polygon_mainnet]:
            self.successful = False
            self.messages.append(f"Network [{self.network}] not supported")
            return

        payload = {
            "id": 1,
            "jsonrpc": "2.0",
            "method": "alchemy_getTokenBalances",
            "params": [self.wallet_address, self.tokens]
        }
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json"
        }

        url = get_api_url(self.network)
        response = requests.post(url, json=payload, headers=headers)

        if response.status_code != 200:
            self.successful = False
            self.messages.append(response.text)
            return

        token_balances = json.loads(response.text)['result']

        if self.update_database:
            children = self.metadata_dao.get_child_web3_docs(self.public_address, self.wallet_address, self.network)
            child_1 = children[0]
            child_1["raw"]["token_balances"] = {'token_balances': token_balances, 'network': self.network,
                                                'created_at': datetime.timestamp(datetime.utcnow())}

            self.metadata_dao.update_doc(doc_id=child_1["_id"], data=child_1)
            self.successful = True
        return token_balances


def get_api_url(network: Network) -> str:
    if network == Network.eth_mainnet:
        return "https://eth-mainnet.alchemyapi.io/v2/" + config['ALCHEMY_API_KEY']['eth_mainnet']
    elif network == Network.polygon_mainnet:
        return "https://polygon-mainnet.g.alchemyapi.io/v2/" + config['ALCHEMY_API_KEY']['polygon']
