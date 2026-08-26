import json
import hashlib
from datetime import datetime, timezone
from typing import List


from dao.base_dao import BaseDao, DBResultError
from config import config
from models.metadata.metadata_models import EntityType, Source
from models.rewards.rewards_model import (
    RewardStatus,
    TaskType,
    safe_reward_failure_message,
)
from commands.dataunions.brainstem.record_projection import (
    brainstem_payout_business_key,
    can_reopen_failed_payout,
)
from utils.get_random_string import get_random_string


class RewardsDao(BaseDao):
    def last_payout_info(self, public_address: str, status: list = []) -> any:
        query = {
            "selector": {
                "public_address": public_address,
                "status": {
                    "$in": status
                }
            },
            "limit": 1,
            "sort": [
                {
                    "updated_at": "desc"
                }
            ]
        }

        result = self.query_data(query)["result"]
        if len(result) == 0:
            return None

        return result[0]

    def create_new_claim(self, public_address: str, start_date: datetime, end_date: datetime,
                         source: Source, entity_type: EntityType = "") -> str:
        doc_id = get_random_string(15)
        create_time = datetime.now().replace(microsecond=0).isoformat()

        document = {
            'public_address': public_address,
            'start_date': start_date.isoformat(),
            'end_date': end_date.isoformat(),
            'created_at': create_time,
            'entity_type': entity_type.name if entity_type else None,
            'status': RewardStatus.CREATED,
            'source': source
        }
        self.save(doc_id, document)
        return doc_id

    def create_new_claim_for_brainstem(self, public_address: str, amount: 0, task_type: TaskType, start_date: datetime = None, end_date: datetime = None) -> str:
        doc_id = get_random_string(15)
        create_time = datetime.now().replace(microsecond=0).isoformat()

        document = {
            'public_address': public_address,
            'created_at': create_time,
            'start_date': start_date.isoformat() if start_date else None,
            'end_date': end_date.isoformat() if end_date else None,
            'task_type': task_type,
            'status': RewardStatus.CREATED,
            'source': Source.brainstem,
            'amount': amount
        }
        self.save(doc_id, document)
        return doc_id

    def create_brainstem_eligibility(
        self, public_address: str, record_id: str, amount: int,
        task_type: TaskType, reward_kind: str
    ) -> str:
        reward_day = datetime.utcnow().date().isoformat()
        digest = hashlib.sha256(
            f"{public_address.lower()}:{record_id}".encode("utf-8")
        ).hexdigest()
        doc_id = f"brainstem-eligibility:{digest}"
        if self.exists(doc_id):
            return doc_id
        document = {
            "document_type": "brainstem_reward_eligibility",
            "public_address": public_address,
            "record_id": record_id,
            "created_at": datetime.utcnow().replace(microsecond=0).isoformat(),
            "reward_day": reward_day,
            "reward_kind": reward_kind,
            "task_type": task_type,
            "status": RewardStatus.CREATED,
            "source": Source.brainstem,
            "amount": amount,
        }
        try:
            self.save(doc_id, document)
        except DBResultError:
            exists, _ = self.get_if_exists(doc_id)
            if not exists:
                raise
        return doc_id

    def void_unclaimed_brainstem_eligibilities(self, record_ids: List[str]) -> int:
        """Void only rewards that have not entered a payout workflow."""
        if not record_ids:
            return 0
        documents = self.query_all({
            "selector": {
                "document_type": "brainstem_reward_eligibility",
                "record_id": {"$in": list(record_ids)},
                "status": RewardStatus.CREATED,
            }
        })
        for document in documents:
            def void_eligibility(current):
                if current.get("status") != RewardStatus.CREATED:
                    return None
                current["status"] = RewardStatus.VOIDED
                current["void_reason"] = "source_record_deleted"
                current["updated_at"] = datetime.utcnow().replace(
                    microsecond=0
                ).isoformat()
                return current

            self.mutate_doc(document["_id"], void_eligibility)
        return len(documents)

    def void_orphaned_brainstem_eligibilities(
        self, public_address: str, surviving_record_ids: List[str]
    ) -> int:
        """Repair unclaimed eligibility after record deletion, including retries."""
        surviving = set(surviving_record_ids)
        documents = self.query_all({
            "selector": {
                "document_type": "brainstem_reward_eligibility",
                "public_address": public_address,
                "status": RewardStatus.CREATED,
            }
        })
        orphaned_ids = [
            document["record_id"]
            for document in documents
            if document.get("record_id") not in surviving
        ]
        return self.void_unclaimed_brainstem_eligibilities(orphaned_ids)

    def create_brainstem_payout_claim_once(
        self, public_address: str, amount: int, entity_ids: List[str],
        claim_day: str = None,
    ):
        claim_day = claim_day or datetime.utcnow().date().isoformat()
        digest = brainstem_payout_business_key(public_address, claim_day)
        doc_id = f"brainstem-claim:{digest}"
        exists, existing = self.get_if_exists(doc_id)
        if exists:
            reopened = [False]

            def reopen_known_failure(document):
                reopened[0] = can_reopen_failed_payout(document)
                if not reopened[0]:
                    return None
                document["status"] = RewardStatus.CALCULATING
                document["amount"] = amount
                document["entity_ids"] = sorted(entity_ids)
                document.pop("reason", None)
                document["updated_at"] = datetime.now().replace(microsecond=0).isoformat()
                return document

            self.mutate_doc(doc_id, reopen_known_failure)
            _, latest = self.get_if_exists(doc_id)
            return doc_id, reopened[0], latest

        create_time = datetime.utcnow().replace(microsecond=0).isoformat()
        document = {
            "document_type": "reward_payout_claim",
            "public_address": public_address,
            "created_at": create_time,
            "start_date": create_time,
            "end_date": create_time,
            "entity_type": EntityType.image,
            "status": RewardStatus.CALCULATING,
            "source": Source.brainstem,
            "amount": amount,
            "entity_ids": sorted(entity_ids),
            "business_key": digest,
            "claim_day": claim_day,
        }
        try:
            self.save(doc_id, document)
            return doc_id, True, document
        except DBResultError:
            exists, existing = self.get_if_exists(doc_id)
            if not exists:
                raise
            return doc_id, False, existing

    def get_brainstem_payout_claims(self, public_address: str):
        return self.query_all({
            "selector": {
                "document_type": "reward_payout_claim",
                "public_address": public_address,
                "source": Source.brainstem,
            },
            "fields": [
                "_id",
                "status",
                "transaction_hash",
                "entity_ids",
                "claim_day",
            ],
        })

    def committed_brainstem_value_entitlement_ids(self, documents):
        """A single commit document is the claimability linearization point."""
        committed = set()
        for commit_id in {
            document.get("commit_id")
            for document in documents
            if document.get("document_type") == "brainstem_value_entitlement"
            and isinstance(document.get("commit_id"), str)
        }:
            exists, commit = self.get_if_exists(commit_id)
            if (
                exists
                and commit.get("document_type") == "brainstem_value_commit"
                and commit.get("status") == "committed"
            ):
                committed.update(commit.get("entitlement_ids", []))
        return committed

    def mark_brainstem_eligibility_paid(self, entity_id: str, claim_id: str):
        def mark_paid(document):
            document["status"] = RewardStatus.PAID
            document["claim_id"] = claim_id
            return document

        return self.mutate_doc(entity_id, mark_paid)

    def update_claim_as_successful(self, claim_id: str, transaction_hash: str, entity_ids=List[str]) -> str:
        def mark_successful(document):
            document['transaction_hash'] = transaction_hash
            document['status'] = RewardStatus.TRANSFER_SUCCEEDED
            document['entity_ids'] = entity_ids
            document['updated_at'] = datetime.now().replace(microsecond=0).isoformat()
            return document

        self.mutate_doc(claim_id, mark_successful)

    def update_claim_to_transferring(self, claim_id: str, amount: int, contract_address: str, sender_address: str,
                                     entity_ids=List[str]):
        def mark_transferring(document):
            document['amount'] = amount
            document['contract_address'] = contract_address
            document['sender_address'] = sender_address
            document['status'] = RewardStatus.TRANSFERRING
            document["entity_ids"] = entity_ids
            document['updated_at'] = datetime.now().replace(microsecond=0).isoformat()
            return document

        self.mutate_doc(claim_id, mark_transferring)

    def update_claim_to_failed(self, claim_id: str, reason: str):
        def mark_failed(document):
            if document.get('status') == RewardStatus.TRANSFER_SUCCEEDED:
                return document
            document['status'] = RewardStatus.FAILED
            document['reason'] = safe_reward_failure_message(reason)
            document['updated_at'] = datetime.now().replace(microsecond=0).isoformat()
            return document

        self.mutate_doc(claim_id, mark_failed)

    def update_claim_transaction_identity(self, claim_id: str, transaction_hash: str):
        def record_transaction(document):
            document["transaction_hash"] = transaction_hash
            document['updated_at'] = datetime.now().replace(microsecond=0).isoformat()
            return document

        self.mutate_doc(claim_id, record_transaction)

    def reconcile_claim_receipt(
        self, claim_id: str, transaction_hash: str, succeeded: bool
    ):
        """Apply only a receipt for the exact transaction already recorded."""
        def apply_receipt(document):
            if document.get("transaction_hash") != transaction_hash:
                raise DBResultError(self.db_name, "transaction_identity_changed")
            document["updated_at"] = datetime.now().replace(
                microsecond=0
            ).isoformat()
            if succeeded:
                document["status"] = RewardStatus.TRANSFER_SUCCEEDED
                document.pop("reason", None)
            else:
                document["status"] = RewardStatus.FAILED
                document["reason"] = "confirmed_chain_revert"
                document["reverted_transaction_hash"] = transaction_hash
                document.pop("transaction_hash", None)
            return document

        return self.mutate_doc(claim_id, apply_receipt)

    
    def get_claim_by_task_type(self, public_address: str, task_type: TaskType):
        query = {
            "selector": {
                "public_address": public_address,
                "task_type": task_type,
                "status": RewardStatus.CREATED
            },
            "limit": 1,
            "sort": [
                {
                    "created_at": "desc"
                }
            ]
        }
        documents = self.query_data(query)["result"]
        if len(documents) == 1:
            return documents[0]
        else:
            return False

    def get_rewards_list(self, public_address: str, entity_type: EntityType, page: int):
        query = {
            "selector": {
                "public_address": public_address,
                "entity_type": entity_type
            },
            "limit": self.page_size,
            "skip": (page - 1) * self.page_size,
            "sort": [
                {
                    "created_at": "desc"
                }
            ]
        }

        result = self.query_data(query)["result"]
        return result
    
    def get_total_earning_list(self, public_address: str, source: Source):
        query = {
            "selector": {
                "public_address": public_address,
                "source": source,
                "status": RewardStatus.TRANSFER_SUCCEEDED
            },
            "sort": [
                {
                    "created_at": "desc"
                }
            ],
            "fields": ["_id", "public_address", "start_date", "end_date", "amount"]
        }

        result = self.query_data(query)["result"]
        return result

    def is_claim_in_progress(self, public_address: str, source: Source, entity_type: EntityType):
        query = {
            "selector": {
                "public_address": public_address,
                "entity_type": entity_type,
                "source": source,
                "status": {"$in": [RewardStatus.CREATED, RewardStatus.TRANSFERRING, RewardStatus.CALCULATING]}
            },
            "limit": 1,
            "skip": 0,
            "sort": [
                {
                    "created_at": "desc"
                }
            ]
        }

        result = self.query_data(query)["result"]
        return len(result) == 1

    def is_one_time_reward_claimed(self, public_address: str, source: Source, entity_type: str):
        query = {
            "selector": {
                "public_address": public_address,
                "entity_type": entity_type,
                "source": source,
                "status": {"$in": [RewardStatus.TRANSFER_SUCCEEDED]}
            },
            "limit": 1,
            "skip": 0,
            "sort": [
                {
                    "created_at": "desc"
                }
            ]
        }

        result = self.query_data(query)["result"]
        return len(result) >= 1

    def update_claim(self, claim_id: str, document: dict):
        document['updated_at'] = datetime.now().replace(microsecond=0).isoformat()
        self.update_doc(doc_id=claim_id, data=document)

    def get_claim_count(self, date: datetime, source: Source, public_address: str) -> int:
        key = f"[\"{public_address}\",\"{source.value}\",{date.year}, {date.month}, {date.day}]"
        query_url = f"/_design/successful-claims-per-day/_view/successful-claims-per-day?key={key}&" \
                    f"reduce=true&group_level=5"
        url = f"{self.base_url}{query_url}"
        payload = {}
        headers = {}

        response = self.client.request("GET", url, headers=headers, data=payload)
        if response.status_code != 200:
            raise DBResultError(self.db_name, response.text)
        data = json.loads(response.text)["rows"]
        if len(data) == 0:
            return 0

        return data[0]["value"]

    def save_record_from_blockchain(self, sender: str, receiver: str, amount: int, block_number: str,
                                    network_name: str, transaction_hash: str, entity_type: EntityType):
        doc_id = get_random_string(15)
        create_time = datetime.now().replace(microsecond=0).isoformat()

        document = {
            'public_address': receiver,
            'sender': sender,
            'block_number': block_number,
            'network_name': network_name,
            'created_at': create_time,
            'entity_type': entity_type,
            'status': RewardStatus.TRANSFER_SUCCEEDED,
            'source': "blockchain",
            'amount': amount,
            'transaction_hash': transaction_hash
        }
        self.save(doc_id, document)
        return doc_id

    def is_transaction_already_saved(self, transaction_hash: str):
        query = {
            "selector": {
                "transaction_hash": transaction_hash
            },
            "limit": 1,
            "skip": 0
        }

        result = self.query_data(query)["result"]
        return len(result) == 1

    def get_total_rewards(self, public_address: str) -> int:
        start_key = f"[\"{public_address}\"]"
        end_key = f"[\"{public_address}\",{{}}]"

        query_url = f"_design/payouts/_view/payouts?start_key={start_key}&end_key={end_key}&" \
                    f"reduce=true&group_level=1"
        url = f"{self.base_url}/{query_url}"
        payload = {}
        headers = {}

        response = self.client.request("GET", url, headers=headers, data=payload)
        if response.status_code != 200:
            raise DBResultError(self.db_name, response.text)
        data = json.loads(response.text)["rows"]
        if len(data) == 0:
            return 0

        return data[0]["value"]

    def get_earning_over_time(self, public_address: str, start_date:str , end_date: str):
        start_key = f"[\"{public_address}\",\"{start_date}\"]"
        end_key = f"[\"{public_address}\",\"{end_date}\"]"
        query_url = f"/_design/payouts/_view/get-earning?start_key={start_key}&end_key={end_key}"
        url = f"{self.base_url}{query_url}"
        headers = {"Content-Type": "application/json"}
        payload = {}
        response = self.client.request("GET", url, headers=headers, data=payload)
        if response.status_code != 200:
            raise DBResultError(self.db_name, response.text)
        data = json.loads(response.text)
        if len(data["rows"]) == 0:
            return 0
        return data["rows"][0]["value"]

    def get_unclaimed_rewards(self, public_address: str):
        """Get all unclaimed rewards for a public address"""
        query = {
            "selector": {
                "public_address": public_address,
                "status": {"$in": [RewardStatus.CREATED, RewardStatus.CALCULATING, RewardStatus.TRANSFERRING]}
            }
        }
        return self.query_data(query)["result"]

    def get_rewards_by_public_address(self, public_address: str):
        """Get all rewards for a public address"""
        query = {
            "selector": {
                "public_address": public_address
            }
        }
        return self.query_data(query)["result"]

rewards_dao = RewardsDao()
rewards_dao.set_config(
    config["couchdb"]["user"],
    config["couchdb"]["password"],
    config["couchdb"]["db_host"],
    config["couchdb"]["rewards_db"],
)
