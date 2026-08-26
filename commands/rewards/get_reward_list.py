from commands.base_command import BaseCommand
from models.metadata.metadata_models import EntityType
from dao.rewards_dao import rewards_dao
from models.rewards.rewards_model import RewardStatus, safe_reward_failure_message


class GetRewardListCommand(BaseCommand):
    def __init__(self, public_address: str, entity_type: EntityType, page: int = 1):
        super(GetRewardListCommand, self).__init__()
        self.public_address = public_address
        self.entity_type = entity_type
        self.page = page

    def execute(self):
        self.successful = True
        result = rewards_dao.get_rewards_list(self.public_address, self.entity_type, self.page)
        transformed_result = []
        for r in result:
            row = {
                'status': r['status'],
                'start_date': r.get('start_date'),
                'end_date': r.get('end_date'),
                'transaction_hash': r.get('transaction_hash'),
                'amount': r.get('amount'),
            }
            if r['status'] == RewardStatus.FAILED:
                row['reason'] = safe_reward_failure_message(r.get('reason'))
            transformed_result.append(row)

        return transformed_result
