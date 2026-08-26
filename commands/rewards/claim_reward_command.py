import time
from datetime import datetime
import re

from eth_account import Account
from eth_account.signers.local import LocalAccount
from requests import HTTPError
from web3.exceptions import ContractLogicError
from web3.middleware import ExtraDataToPOAMiddleware

from commands.rewards.calculate_reward import (
    CalculateRewardCommand,
    CannotClaimRewardException,
    brainstem_reward_commitment,
)
from commands.rewards.sender_lock import reward_sender_lock
from commands.base_command import BaseCommand
from config import config
from web3 import Web3, HTTPProvider
from dao.users_dao import user_dao
from dao.base_dao import DBResultError
from dao.metadata_dao import image_metadata_dao
from models.metadata.metadata_models import EntityType, Source, EntityRewardStatus
from dao.rewards_dao import rewards_dao
import logging

from models.rewards.rewards_model import (
    ClaimRewardErrorMessages,
    RewardStatus,
    safe_reward_failure_message,
)
from utils.abi.erc20_abi import ERC20_ABI
from commands.dataunions.brainstem.consent import has_legacy_mobile_consent
from commands.dataunions.brainstem.record_projection import (
    has_unresolved_payout,
    rewards_allowed_by_consent,
    successful_payout_pending_projection,
)


def fail_claim(command, claim_id, error, client_message=None):
    safe_message = safe_reward_failure_message(error)
    command.messages.append(client_message or safe_message)
    rewards_dao.update_claim_to_failed(claim_id, safe_message)
    logging.error(
        "%s failed (%s): %s",
        type(command).__name__,
        type(error).__name__,
        safe_message,
    )


class ClaimRewardCommand(CalculateRewardCommand):

    def __init__(self, public_address: str, source: Source, entity_type: EntityType = None, amount: str = None, expected_amount_raw=None, expected_eligibility_commitment_sha256=None):
        super(ClaimRewardCommand, self).__init__(public_address, source, entity_type)
        self.public_address = public_address
        self.entity_type = entity_type
        self.validate_input()
        self.min_amount = 1
        self.amount = amount
        if expected_amount_raw is None:
            self.expected_amount_raw = None
        elif (
            isinstance(expected_amount_raw, str)
            and re.fullmatch(r"[0-9]{1,36}", expected_amount_raw)
        ):
            self.expected_amount_raw = int(expected_amount_raw)
        else:
            raise ValueError("expected_amount_raw must be a decimal string")
        if expected_eligibility_commitment_sha256 is None:
            self.expected_eligibility_commitment_sha256 = None
        elif (
            isinstance(expected_eligibility_commitment_sha256, str)
            and re.fullmatch(r"[0-9a-f]{64}", expected_eligibility_commitment_sha256)
        ):
            self.expected_eligibility_commitment_sha256 = (
                expected_eligibility_commitment_sha256
            )
        else:
            raise ValueError("expected eligibility commitment must be lowercase SHA-256")
        if (self.expected_amount_raw is None) != (
            self.expected_eligibility_commitment_sha256 is None
        ):
            raise ValueError("expected amount and eligibility commitment must be provided together")
        self.reward_config = {
            Source.wedatanation: {
                "max_daily_claims": 10,
                "minimum_amount": 1,
                "maximum_amount": 100 ** 18
            },
            Source.default: {
                "max_daily_claims": 1,
                "minimum_amount": 1,
                "maximum_amount": 100 ** 18
            },
            Source.brainstem: {
                "max_daily_claims": 1,
                "minimum_amount": 1,
                "maximum_amount": 100 ** 18
            },
            Source.recyclium: {
                "max_daily_claims": 1,
                "minimum_amount": 1,
                "maximum_amount": 100 ** 18
            },
            Source.ncight: {
                "max_daily_claims": 1,
                "minimum_amount": 1,
                "maximum_amount": 100 ** 18
            }
        }

    def execute(self):
        self.successful = False

        if self.source == Source.brainstem:
            return self.execute_brainstem_claim()

        if rewards_dao.is_claim_in_progress(self.public_address, self.source, self.entity_type):
            self.messages.append(ClaimRewardErrorMessages.ALREADY_IN_PROGRESS)
            return

        max_claim_per_day = self.reward_config[self.source]["max_daily_claims"]
        if rewards_dao.get_claim_count(datetime.utcnow(), self.source, self.public_address) >= max_claim_per_day:
            self.messages.append(ClaimRewardErrorMessages.EXCEEDS_DAILY_LIMIT)
            return
            

        start_date = self.get_claim_start_date()
        claim_id = rewards_dao.create_new_claim(self.public_address, start_date, self.end_date,
                                                self.source, self.entity_type)

        try:
            entity_ids = None
            amount = 0

            if self.source == Source.wedatanation:
                amount, entity_ids = self.calculate_wedatanation_reward()

            elif self.source == Source.recyclium:
                amount = self.amount

            else:
                if start_date.date() >= datetime.today().date():
                    raise CannotClaimRewardException(f'Last reward payout date is today.')

                amount = self.calculate_amount_in_wei(start_date=start_date)

            if amount == 0:
                raise CannotClaimRewardException(ClaimRewardErrorMessages.ZERO_AMOUNT)

            if self.min_amount > amount:
                raise CannotClaimRewardException(ClaimRewardErrorMessages.AMOUNT_TOO_SMALL)

            sender_address = Account.from_key(config["rewards"]["account_private_key"]).address
            rewards_dao.update_claim_to_transferring(claim_id, amount, config["rewards"]["token_contract_address"],
                                                     sender_address, entity_ids=entity_ids)
            transaction_hash = self.transfer(amount, claim_id)
            rewards_dao.update_claim_as_successful(claim_id, transaction_hash, entity_ids=entity_ids)
            logging.info("Reward transfer transaction for user [%s]: [%s]", self.public_address, transaction_hash)
            if self.source == Source.wedatanation:
                for entity_id in entity_ids:
                    parent_doc = image_metadata_dao.get_doc_by_id(entity_id)
                    parent_doc["reward_information"]["reward_status"] = EntityRewardStatus.paid
                    parent_doc["reward_information"]["claim_id"] = claim_id
                    image_metadata_dao.update_doc(doc_id=parent_doc["_id"], data=parent_doc)

                self.transfer_gas_if_needed()
            
            self.successful = True
            return transaction_hash

        except HTTPError as err:
            fail_claim(self, claim_id, err)

        except DBResultError as err:
            fail_claim(self, claim_id, err, "Internal database error")

        except CannotClaimRewardException as err:
            fail_claim(self, claim_id, err)

        except ContractLogicError as err:
            fail_claim(self, claim_id, err)

        except Exception as err:
            fail_claim(self, claim_id, err)

    def execute_brainstem_claim(self):
        users = user_dao.get_by_public_address(self.public_address).get("result", [])
        if len(users) != 1:
            self.messages.append("Brainstem user was not found")
            return None
        has_reward_consent = has_legacy_mobile_consent(users[0])

        payout_claims = rewards_dao.get_brainstem_payout_claims(self.public_address)
        reward_documents = rewards_dao.query_all({
            'selector': {
                'public_address': self.public_address,
                "source": Source.brainstem,
            }
        })
        reward_documents = rewards_allowed_by_consent(
            reward_documents, has_reward_consent
        )
        claimable_documents = [
            document for document in reward_documents
            if document.get("status") == RewardStatus.CREATED
        ]
        repaired_transaction_hash = None
        completed_claim = successful_payout_pending_projection(
            claimable_documents, payout_claims
        )
        if completed_claim:
            for entity_id in completed_claim.get("entity_ids", []):
                try:
                    rewards_dao.mark_brainstem_eligibility_paid(
                        entity_id, completed_claim["_id"]
                    )
                except Exception as err:
                    logging.error(
                        "Reward projection repair failed (%s): %s",
                        type(err).__name__,
                        safe_reward_failure_message(err),
                    )
            repaired_transaction_hash = completed_claim.get("transaction_hash")

        today = datetime.utcnow().date().isoformat()
        completed_today = next(
            (
                claim
                for claim in payout_claims
                if claim.get("status") == RewardStatus.TRANSFER_SUCCEEDED
                and claim.get("claim_day") == today
                and claim.get("transaction_hash")
            ),
            None,
        )
        if completed_today:
            self.successful = True
            return completed_today["transaction_hash"]

        if has_unresolved_payout(payout_claims):
            self.messages.append(ClaimRewardErrorMessages.RECONCILIATION_REQUIRED)
            return None

        max_claim_per_day = self.reward_config[Source.brainstem]["max_daily_claims"]
        if rewards_dao.get_claim_count(
            datetime.utcnow(), Source.brainstem, self.public_address
        ) >= max_claim_per_day:
            if repaired_transaction_hash:
                self.successful = True
                return repaired_transaction_hash
            self.messages.append(ClaimRewardErrorMessages.EXCEEDS_DAILY_LIMIT)
            return None

        amount, entity_ids = self.calculate_brainstem_reward(reward_documents)
        if amount == 0 or not entity_ids:
            if repaired_transaction_hash:
                self.successful = True
                return repaired_transaction_hash
            self.messages.append(ClaimRewardErrorMessages.ZERO_AMOUNT)
            return None
        if self.expected_amount_raw is not None and amount != self.expected_amount_raw:
            self.messages.append(ClaimRewardErrorMessages.AMOUNT_CHANGED)
            return None
        # Optional If-Match guard for canaries and updated clients. Omitting it
        # never supplies payout inputs: wallet, amount, and eligibility stay
        # server-owned so released mobile clients remain compatible.
        if (
            self.expected_eligibility_commitment_sha256 is not None
            and brainstem_reward_commitment(amount, entity_ids)
            != self.expected_eligibility_commitment_sha256
        ):
            self.messages.append(ClaimRewardErrorMessages.ELIGIBILITY_CHANGED)
            return None

        claim_id = None
        transaction_hash = None
        transfer_succeeded = False
        try:
            claim_id, created, existing = rewards_dao.create_brainstem_payout_claim_once(
                self.public_address, amount, entity_ids
            )
            if not created:
                if existing.get("status") == RewardStatus.TRANSFER_SUCCEEDED:
                    transaction_hash = existing.get("transaction_hash")
                    transfer_succeeded = True
                    for entity_id in existing.get("entity_ids", []):
                        rewards_dao.mark_brainstem_eligibility_paid(
                            entity_id, claim_id
                        )
                    self.successful = True
                    return transaction_hash
                self.messages.append(ClaimRewardErrorMessages.RECONCILIATION_REQUIRED)
                return None

            sender_address = Account.from_key(
                config["rewards"]["account_private_key"]
            ).address
            rewards_dao.update_claim_to_transferring(
                claim_id,
                amount,
                config["rewards"]["token_contract_address"],
                sender_address,
                entity_ids=entity_ids,
            )
            transaction_hash = self.transfer(amount, claim_id)
            rewards_dao.update_claim_as_successful(
                claim_id, transaction_hash, entity_ids=entity_ids
            )
            transfer_succeeded = True
            for entity_id in entity_ids:
                rewards_dao.mark_brainstem_eligibility_paid(entity_id, claim_id)
            self.successful = True
            return transaction_hash
        except Exception as err:
            safe_message = safe_reward_failure_message(err)
            self.messages.append(safe_message)
            if claim_id and not transfer_succeeded:
                rewards_dao.update_claim_to_failed(claim_id, safe_message)
            logging.error(
                "Brainstem reward claim failed (%s): %s",
                type(err).__name__,
                safe_message,
            )
            if transfer_succeeded:
                self.successful = True
                return transaction_hash
            return None

    def transfer(self, amount: int, claim_id: str = None) -> str:
        # Constants
        json_rpc_url = config["rewards"]["network_url"]
        rpc_timeout = config["rewards"].getfloat("rpc_timeout_seconds", 30)
        receipt_timeout = config["rewards"].getfloat("receipt_timeout_seconds", 90)
        web3 = Web3(HTTPProvider(json_rpc_url, request_kwargs={"timeout": rpc_timeout}))
        chain_id = int(config["rewards"]["chain_id"])
        if config["rewards"]["network"] == "mumbai":
            web3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
            chain_id = 80001
        token_contract_address = Web3.to_checksum_address(config["rewards"]["token_contract_address"])
        sender_account_private_key = config["rewards"]["account_private_key"]

        account: LocalAccount = Account.from_key(sender_account_private_key)
        contract = web3.eth.contract(address=token_contract_address, abi=ERC20_ABI)
        assert web3.is_checksum_address(self.public_address), f"Not a valid address: {self.public_address}"
        with reward_sender_lock():
            nonce = web3.eth.get_transaction_count(account.address, "pending")
            txn = contract.functions.transfer(
                self.public_address, amount
            ).build_transaction(
                {'nonce': nonce, 'gas': 100000, 'chainId': chain_id}
            )
            signed_txn = web3.eth.account.sign_transaction(
                txn, private_key=sender_account_private_key
            )
            tx_hash = signed_txn.hash.hex()
            try:
                web3.eth.send_raw_transaction(signed_txn.raw_transaction)
            except ValueError as err:
                # JSON-RPC validation failures are definite rejections. A known
                # transaction is the exception: the same bytes were accepted by a
                # node already, so continue with receipt reconciliation.
                message = str(err).lower()
                if not any(marker in message for marker in (
                    "already known", "known transaction", "already imported"
                )):
                    raise
            except Exception:
                # Transport failures after writing the request are ambiguous. Keep
                # the deterministic signed hash so operations can reconcile before
                # another payout is attempted.
                if claim_id:
                    rewards_dao.update_claim_transaction_identity(claim_id, tx_hash)
                raise
            if claim_id:
                rewards_dao.update_claim_transaction_identity(claim_id, tx_hash)

        tx_receipt = web3.eth.wait_for_transaction_receipt(
            tx_hash, timeout=receipt_timeout, poll_latency=5
        )

        if tx_receipt is not None and tx_receipt['status'] != 1:
            raise CannotClaimRewardException(f"Transaction transaction receipt status [{tx_receipt['status']}]")
        tx_hash = signed_txn.hash.hex()
        return tx_hash

    def transfer_gas_if_needed(self):
        # send gas to user only 1 time
        user_obj = user_dao.get_by_public_address(self.public_address)["result"][0]

        if user_obj.get("gas_transferred") is True:
            return

        logging.info("Transferring gas token to user [%s]", self.public_address)
        # now transfer some gas to user.
        amount = 0.0001
        json_rpc_url = config["rewards"]["network_url"]
        web3 = Web3(HTTPProvider(json_rpc_url))
        chain_id = int(config["rewards"]["chain_id"])
        if config["rewards"]["network"] == "mumbai":
            web3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
            chain_id = 80001
        sender_account_private_key = config["rewards"]["account_private_key"]

        account: LocalAccount = Account.from_key(sender_account_private_key)

        assert web3.is_checksum_address(self.public_address), f"Not a valid address: {self.public_address}"
        with reward_sender_lock():
            nonce = web3.eth.get_transaction_count(account.address, "pending")
            tx = {
                "type": 2,
                "gas": 100000,
                "maxFeePerGas": 2000000000,
                "maxPriorityFeePerGas": 2000000000,
                "nonce": nonce,
                'to': self.public_address,
                "value": Web3.to_wei(amount, 'ether'),
                "chainId": chain_id,
            }
            signed_tx = web3.eth.account.sign_transaction(
                tx, private_key=sender_account_private_key
            )
            tx_hash = signed_tx.hash.hex()
            web3.eth.send_raw_transaction(signed_tx.raw_transaction)
        logging.info("Gas transfer: Getting transaction receipt for tx [%s]", tx_hash)

        tx_receipt = web3.eth.wait_for_transaction_receipt(signed_tx.hash.hex())
        if tx_receipt is not None and tx_receipt['status'] != 1:
            raise CannotClaimRewardException(f"Transaction receipt status [{tx_receipt['status']}] when sending gas")
        # get transaction hash
        logging.info("Gas sent to user [%s]", self.public_address)

        user_obj["gas_transferred"] = True
        user_obj["gas_transfer_tx"] = tx_hash

        user_dao.save(user_obj["_id"], user_obj)

        return tx_hash

class ClaimRewardByQRCodeCommand(BaseCommand):

    def __init__(self, public_address: str, source: Source, entity_type: EntityType = None, amount: str = None):
        super(ClaimRewardByQRCodeCommand, self).__init__()
        self.public_address = public_address
        self.entity_type = entity_type
        self.source = source
        self.min_amount = 1
        self.amount = amount
        
    def execute(self):
        self.successful = False

        claim_id = rewards_dao.create_new_claim(self.public_address, datetime.now(), datetime.now(),
                                                self.source, self.entity_type)

        try:
            entity_ids = None
            amount = self.amount * (10 ** 18)

            sender_address = Account.from_key(config["rewards"]["account_private_key"]).address
            rewards_dao.update_claim_to_transferring(claim_id, amount, config["rewards"]["token_contract_address"],
                                                     sender_address, entity_ids=entity_ids)
            transaction_hash = self.transfer(amount)
            rewards_dao.update_claim_as_successful(claim_id, transaction_hash, entity_ids=entity_ids)
            logging.info("Reward transfer transaction for user [%s]: [%s]", self.public_address, transaction_hash)

            self.successful = True
            return transaction_hash

        except HTTPError as err:
            fail_claim(self, claim_id, err)

        except DBResultError as err:
            fail_claim(self, claim_id, err, "Internal database error")

        except CannotClaimRewardException as err:
            fail_claim(self, claim_id, err)

        except ContractLogicError as err:
            fail_claim(self, claim_id, err)

        except Exception as err:
            fail_claim(self, claim_id, err)

    def transfer(self, amount: int) -> str:
        # Constants
        json_rpc_url = config["rewards"]["network_url"]
        web3 = Web3(HTTPProvider(json_rpc_url))
        chain_id = int(config["rewards"]["chain_id"])
        if config["rewards"]["network"] == "mumbai":
            web3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
            chain_id = 80001
        token_contract_address = Web3.to_checksum_address(config["rewards"]["token_contract_address"])
        sender_account_private_key = config["rewards"]["account_private_key"]

        account: LocalAccount = Account.from_key(sender_account_private_key)
        contract = web3.eth.contract(address=token_contract_address, abi=ERC20_ABI)
        assert web3.is_checksum_address(self.public_address), f"Not a valid address: {self.public_address}"
        with reward_sender_lock():
            nonce = web3.eth.get_transaction_count(account.address, "pending")
            txn = contract.functions.transfer(
                self.public_address, int(amount)
            ).build_transaction(
                {'nonce': nonce, 'gas': 100000, 'chainId': chain_id}
            )
            signed_txn = web3.eth.account.sign_transaction(
                txn, private_key=sender_account_private_key
            )
            web3.eth.send_raw_transaction(signed_txn.raw_transaction)
            tx_hash = signed_txn.hash.hex()
        max_attempts = 3
        tx_receipt = None
        for i in range(max_attempts):
            time.sleep(5)
            logging.info("Attempt [%s] to get receipt for transaction [%s]", i, tx_hash)
            tx_receipt = web3.eth.wait_for_transaction_receipt(tx_hash)
            if tx_receipt is not None:
                logging.info("Found tx_receipt [%s]", tx_receipt)
                break

        if tx_receipt is not None and tx_receipt['status'] != 1:
            raise CannotClaimRewardException(f"Transaction transaction receipt status [{tx_receipt['status']}]")
        tx_hash = signed_txn.hash.hex()
        return tx_hash

    def transfer_gas_if_needed(self):
        # send gas to user only 1 time
        user_obj = user_dao.get_by_public_address(self.public_address)["result"][0]

        if user_obj.get("gas_transferred") is True:
            return

        logging.info("Transferring gas token to user [%s]", self.public_address)
        # now transfer some gas to user.
        amount = 0.0001
        json_rpc_url = config["rewards"]["network_url"]
        web3 = Web3(HTTPProvider(json_rpc_url))
        chain_id = int(config["rewards"]["chain_id"])
        if config["rewards"]["network"] == "mumbai":
            web3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
            chain_id = 80001
        sender_account_private_key = config["rewards"]["account_private_key"]

        account: LocalAccount = Account.from_key(sender_account_private_key)

        assert web3.is_checksum_address(self.public_address), f"Not a valid address: {self.public_address}"
        with reward_sender_lock():
            nonce = web3.eth.get_transaction_count(account.address, "pending")
            tx = {
                "type": 2,
                "gas": 100000,
                "maxFeePerGas": 2000000000,
                "maxPriorityFeePerGas": 2000000000,
                "nonce": nonce,
                'to': self.public_address,
                "value": Web3.to_wei(amount, 'ether'),
                "chainId": chain_id,
            }
            signed_tx = web3.eth.account.sign_transaction(
                tx, private_key=sender_account_private_key
            )
            tx_hash = signed_tx.hash.hex()
            web3.eth.send_raw_transaction(signed_tx.raw_transaction)
        logging.info("Gas transfer: Getting transaction receipt for tx [%s]", tx_hash)

        tx_receipt = web3.eth.wait_for_transaction_receipt(signed_tx.hash.hex())
        if tx_receipt is not None and tx_receipt['status'] != 1:
            raise CannotClaimRewardException(f"Transaction receipt status [{tx_receipt['status']}] when sending gas")
        # get transaction hash
        logging.info("Gas sent to user [%s]", self.public_address)

        user_obj["gas_transferred"] = True
        user_obj["gas_transfer_tx"] = tx_hash

        user_dao.save(user_obj["_id"], user_obj)

        return tx_hash
