import requests

from models.UsageFlag import UsageFlag
from .base_dao import BaseDao
import json
from datetime import datetime
import random
from web3.auto import w3
import logging
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
            logging.info("Nonce found [{0}] for address [{1}]".format(data["result"][0]["nonce"], public_address))
            return {"status": "exists", "nonce": data["result"][0]["nonce"]}

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
        document["is_access_blocked"] = False
        document['usage_flag'] = UsageFlag.UNKNOWN.name

        self.save(doc_id, document)
        return nonce

    def verify_signature(self, public_address, signature):

        selector = {"selector": {"_id": {"$gt": None}, "public_address": public_address}}
        data = self.query_data(selector)

        if len(data["result"]) != 1:
            logging.info("Address not [{}] found in [{}] db".format(public_address, self.db_name))
            return False

        nonce = data["result"][0]["nonce"]
        message = encode_defunct(text=str(nonce))
        try:
            signer = w3.eth.account.recover_message(message, signature=signature)
            if public_address == signer:
                return True
            else:
                logging.info("Signature verification failed for [{}]. Signer not matched".format(public_address))
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

    def is_access_blocked(self, public_address):
        documents = self.get_by_public_address(public_address)["result"]
        if len(documents) != 1:
            return False
        return documents[0]["is_access_blocked"]

    def block_access(self, public_address):
        documents = self.get_by_public_address(public_address)["result"]
        if len(documents) != 1:
            return

        documents[0]["is_access_blocked"] = True
        documents[0]["updated_at"] = datetime.timestamp(datetime.now())
        self.update_doc(documents[0]["_id"], documents[0])

    def unblock_access(self, public_address):
        documents = self.get_by_public_address(public_address)["result"]
        if len(documents) != 1:
            return

        documents[0]["is_access_blocked"] = False
        documents[0]["updated_at"] = datetime.timestamp(datetime.now())
        self.update_doc(documents[0]["_id"], documents[0])

    def set_usage_flag(self, public_address, flag):
        documents = self.get_by_public_address(public_address)["result"]
        if len(documents) != 1:
            return

        documents[0]["usage_flag"] = flag
        documents[0]["updated_at"] = datetime.timestamp(datetime.now())
        self.update_doc(documents[0]["_id"], documents[0])

    def get_usage_flag(self, public_address):
        documents = self.get_by_public_address(public_address)["result"]
        if len(documents) != 1:
            return

        return documents[0].get("usage_flag")
