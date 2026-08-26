from typing import List
import hashlib
import json

from commands.base_command import BaseCommand
from commands.metadata.create_new_entity.create_brainstem_entity import EntitySubType
from dao.metadata_dao import image_metadata_dao
from dao.rewards_dao import rewards_dao
from dao.users_dao import user_dao
from models.metadata.metadata_models import EntityType, Source
from datetime import datetime, timedelta
from dateutil import parser
from models.rewards.rewards_model import RewardStatus
from web3 import Web3
from commands.dataunions.brainstem.record_projection import (
    select_claimable_eligibilities,
)


def calculate_brainstem_reward_amount(public_address, claims, dao):
    payout_claims = dao.get_brainstem_payout_claims(public_address)
    paid_entity_ids = {
        entity_id
        for payout in payout_claims
        if payout.get("status") == RewardStatus.TRANSFER_SUCCEEDED
        for entity_id in payout.get("entity_ids", [])
    }
    committed_value_ids = dao.committed_brainstem_value_entitlement_ids(claims)
    selected = select_claimable_eligibilities(
        claims, paid_entity_ids, committed_value_ids
    )
    selected = [claim for claim in selected if "amount" in claim]
    amount = sum(claim.get("amount", 0) for claim in selected)
    return Web3.to_wei(amount, "ether"), [claim["_id"] for claim in selected]


def brainstem_reward_commitment(amount, entity_ids):
    return hashlib.sha256(
        json.dumps(
            {"amountRaw": str(amount), "entityIds": sorted(entity_ids)},
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()


class CalculateRewardCommand(BaseCommand):

    def __init__(self, public_address: str, source: Source, entity_type: EntityType, end_date_delta: int = 1):
        super(CalculateRewardCommand, self).__init__(public_address)
        self.entity_type = entity_type

        self.upload_reward = 0.1
        self.tag_annotations_reward = 0.1
        self.text_annotations_reward = 0.1
        self.verifications_rewards = 0.1
        self.default_start_date = datetime.strptime('1-1-2021', '%d-%m-%Y')
        self.end_date = datetime.utcnow().today() - timedelta(days=end_date_delta)
        self.source = source
        self.end_date_delta = end_date_delta

    def execute(self):
        if self.source == Source.wedatanation:
            self.successful = True
            amount, entity_ids = self.calculate_wedatanation_reward()
            return {'amount': amount, "app": self.source, "entity_ids": entity_ids}

        if self.source == Source.recyclium:
            self.successful = True
            user = user_dao.get_by_public_address(self.public_address)['result'][0]
            return {'amount': user['rewards'], 'app': self.source, 'entity_ids': []}

        if self.source == Source.brainstem:
            self.successful = True
            amount, claim_ids = self.calculate_brainstem_reward()
            return {'amount': amount, "app": self.source, "entity_ids": claim_ids}

        claim_start_date = self.get_claim_start_date()

        if claim_start_date.date() == datetime.utcnow().date() and self.end_date_delta == 1:
            self.successful = False
            self.messages.append("Claim start date cannot be today.")
            return

        amount = self.calculate_amount_in_wei(claim_start_date)
        self.successful = True
        format_code = "%d-%m-%Y"
        return {'amount': amount, 'start_date': claim_start_date.strftime(format_code),
                'end_date': self.end_date.strftime(format_code), "app": self.source}

    def calculate_amount_in_wei(self, start_date: datetime = None) -> int:
        if start_date is None:
            start_date = self.default_start_date

        result = image_metadata_dao.get_user_stats_count(self.public_address, self.entity_type, start_date,
                                                            self.end_date)

        amount = self.upload_reward * result['uploads'] + self.tag_annotations_reward * result[
            'tag_annotations'] + self.text_annotations_reward * result[
                        'text_annotations'] + self.verifications_rewards * result[
                        'verifications']
        amount = int(amount * 10 ** 18)
        return amount

    def get_claim_start_date(self) -> datetime:

        status_list = [RewardStatus.CREATED, RewardStatus.TRANSFERRING, RewardStatus.TRANSFER_SUCCEEDED]
        last_payout_info = rewards_dao.last_payout_info(self.public_address, status_list)

        if last_payout_info is None:
            return self.default_start_date
        last_payout_end_date = parser.parse(last_payout_info['end_date'])
        return last_payout_end_date + timedelta(days=1)
    
    def calculate_wedatanation_reward(self) -> (int, List[str]):

        rewards_dict = {
            # Dict keys 0 = 1st upload, 1st index = 2nd upload and so on.
            "upload": {
                0: 2.5,
                1: 1.25,
                2: 1.5,
                3: 1.75,
                4: 2,
                5: 2.25
            }
        }

        start_key = f'["{self.public_address}"]'
        end_key = f'["{self.public_address}",{{}}]'

        result = image_metadata_dao.query_view_by_key_range("reward-status", "wedatanation", start_key, end_key, 0)

        amount = 0
        entity_ids = []
        for row in result['rows']:
            value = row["value"]
            if value["type"] == "upload":
                amount += rewards_dict["upload"].get(value["count"], 0)
                entity_ids.append(row["value"]["id"])
        amount = Web3.to_wei(amount, 'ether')
        return amount, entity_ids

    def calculate_brainstem_reward(self, claims=None) -> int:
        if claims is None:
            claims = rewards_dao.query_all({
                'selector': {
                    'public_address': self.public_address,
                    "source": Source.brainstem
                }
            })
        return calculate_brainstem_reward_amount(
            self.public_address, claims, rewards_dao
        )

class CannotClaimRewardException(Exception):
    def __init__(self, message: str):
        self.message = message
        super().__init__(self.message)

    def __str__(self):
        return f'{self.message}'
