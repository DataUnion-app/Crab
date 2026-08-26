import logging
import random

from web3.auto import w3
from eth_account.messages import encode_defunct

from commands.dataunions.wedatanation.web3_data_loaders import SaveTokenBalancesByUser
from dao.users_dao import user_dao
from commands.base_command import BaseCommand
from commands.dataunions.wedatanation.add_json_entity_command import AddNewJsonEntityCommand
from dao.base_dao import DBResultError
from dao.metadata_dao import image_metadata_dao
from models.metadata.metadata_models import EntitySubType, Network


class UpdateWeb3MonetizationWalletAddress(BaseCommand):
    def __init__(self, public_address: str, wallet_address: str, signature: str, network: Network = Network.default):
        super(UpdateWeb3MonetizationWalletAddress, self).__init__(public_address)
        self.wallet_address = wallet_address
        self.signature = signature
        self.metadata_dao = image_metadata_dao
        self.user_dao = user_dao
        self.network = network

    def execute(self):
        # Check the if web3 entity exists
        doc_id = None
        try:
            is_valid = self.verify_signature()
            if not is_valid:
                self.messages.append("Invalid signature")
                return
            query = {
                "selector": {
                    "uploaded_by": self.public_address,
                    "json_entity_type": "web3",
                    "raw": {
                        "wallet_address": self.wallet_address,
                        "network": self.network
                    }
                }
            }
            result = self.metadata_dao.query_data(query)['result']
            if len(result) == 0:
                c = AddNewJsonEntityCommand(self.public_address, EntitySubType.web3, parent_data={
                    "wallet_address": self.wallet_address,
                    "network": self.network
                }, raw={})
                doc_id = c.execute()

                save_token_balances_command = SaveTokenBalancesByUser(public_address=self.public_address,
                                                                      wallet_address=self.wallet_address,
                                                                      network=self.network)
                save_token_balances_command.execute()
                if not save_token_balances_command.successful:
                    logging.info("Unable to load user balance %s", save_token_balances_command.messages)
            else:
                # Entity already exists. Update the wallet address
                self.successful = False
                self.messages.append(f"Already exists ID : [{result[0]['_id']}]")
                return
        except DBResultError as e:
            # Entity does not exist
            logging.exception("Unable to set web3 wallet address", exc_info=e)
            self.messages.append(str(e))
            return

        self.successful = True
        return doc_id

    def verify_signature(self):
        try:
            user = self.user_dao.get_by_public_address(self.public_address)["result"][0]
            message = user["web3_wallets_nonce"][self.wallet_address]["nonce"]
            message = encode_defunct(text=message)
            signer = w3.eth.account.recover_message(message, signature=self.signature)
            if w3.to_checksum_address(self.wallet_address) == w3.to_checksum_address(signer):
                return True
            else:
                logging.info(
                    "Signature verification failed for [{}]. Signer not matched".format(
                        self.public_address
                    )
                )
        except Exception as e:
            logging.exception(
                "Signature verification failed for [{}]".format(self.public_address),
                exc_info=e
            )
            return False


class GetWeb3WalletMonetizationNonce(BaseCommand):
    def __init__(self, public_address: str, wallet_address: str):
        super(GetWeb3WalletMonetizationNonce, self).__init__(public_address)
        self.wallet_address = wallet_address
        self.user_dao = user_dao

    def execute(self):
        users = user_dao.get_by_public_address(self.public_address)["result"]
        if len(users) != 1:
            self.messages.append("Unable to fetch user")
            return
        user = users[0]
        system_random = random.SystemRandom()
        nonce = str(system_random.randint(100000000, 9999999999999))

        web3_wallets_nonce = user.get("web3_wallets_nonce")

        if not web3_wallets_nonce:
            user["web3_wallets_nonce"] = {
                self.wallet_address: {
                    "nonce": nonce
                }
            }
        else:
            user["web3_wallets_nonce"][self.wallet_address] = {"nonce": nonce}

        self.user_dao.update_doc(user["_id"], user)
        self.successful = True
        return nonce
