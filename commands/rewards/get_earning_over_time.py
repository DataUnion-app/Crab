from commands.base_command import BaseCommand
from dao.rewards_dao import rewards_dao
from datetime import datetime

class GetEarningOverTimeCommand(BaseCommand):
    def __init__(self, public_address: str, start_date: str, end_date: str):
        super(GetEarningOverTimeCommand, self).__init__()
        self.public_address = public_address
        self.start_date = start_date
        self.end_date = end_date

    def execute(self):
        start_date = datetime.strptime(self.start_date, "%Y-%m-%d")
        end_date = datetime.strptime(self.end_date, "%Y-%m-%d")
        result = rewards_dao.get_earning_over_time(self.public_address, self.start_date, self.end_date)
        return result
