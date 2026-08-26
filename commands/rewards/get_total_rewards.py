from commands.base_command import BaseCommand
from dao.rewards_dao import rewards_dao

class GetTotalRewardsCommand(BaseCommand):
    def __init__(self, public_address: str):
        super(GetTotalRewardsCommand, self).__init__()
        self.public_address = public_address

    def execute(self):
        self.successful = True
        result = rewards_dao.get_total_rewards(self.public_address)
        return result
