import requests
from .BaseDao import BaseDao
import json
from datetime import datetime
import random
from web3.auto import w3
from eth_account.messages import defunct_hash_message, encode_defunct
from utils.get_random_string import get_random_string


class UsersDao(BaseDao):

    def get_by_public_address(self, public_address):
        selector = {"selector": {"_id": {"$gt": None}, "public_address": public_address}}
        return self.query_data(selector)

    def get_nonce(self, public_address):
        selector = {"selector": {"_id": {"$gt": None}, "public_address": public_address}}
        data = self.query_data(selector)

        if len(data["result"]) == 1:
            print("Nonce found [{0}] for address [{1}]".format(data["result"][0]["nonce"], public_address))
            return {"status": "exists", "nonce": data["result"][0]["nonce"]}

        print("Nonce not found for address [{}]".format(public_address))
        return {"status": "not found"}

    def get_nonce_if_not_exists(self, public_address):
        selector = {"selector": {"_id": {"$gt": None}, "public_address": public_address}}
        data = self.query_data(selector)

        if len(data["result"]) == 1:
            return data["result"][0]["nonce"]

        system_random = random.SystemRandom()
        nonce = system_random.randint(100000000, 9999999999999)
        doc_id = get_random_string()

        document = dict()
        document["created_at"] = datetime.timestamp(datetime.now())
        document["public_address"] = public_address
        document["nonce"] = nonce
        document["status"] = "new"
        document["is_blocked"] = False

        self.save(doc_id, document)
        return nonce

    def verify_signature(self, public_address, signature):

        selector = {"selector": {"_id": {"$gt": None}, "public_address": public_address}}
        data = self.query_data(selector)

        if len(data["result"]) != 1:
            print("Address not [{}] found in [{}] db".format(public_address, self.db_name))
            return False

        nonce = data["result"][0]["nonce"]
        message = encode_defunct(text=str(nonce))
        try:
            signer = w3.eth.account.recover_message(message, signature=signature)
            if public_address == signer:
                return True
            else:
                print("Signature verification failed for [{}]. Signer not matched".format(public_address))
        except:
            logging.info("Signature verification failed for [{}]".format(public_address))
            return False

        return False

    def update_nonce(self, public_address):
        documents = self.get_by_public_address(public_address)["result"]
        if len(documents) != 1:
            return False

        system_random = random.SystemRandom()
        nonce = system_random.randint(100000000, 9999999999999)
        documents[0]["nonce"] = nonce
        self.update_doc(documents[0]["_id"], documents[0])
        return True
