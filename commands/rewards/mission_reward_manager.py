from typing import List
from dao.missions_dao import missions_dao
from commands.base_command import BaseCommand
from models.missions import MissionRewardStatus


class MarkMissionsAsPaid(BaseCommand):
    def __init__(self, payment_info: List[dict]):
        super(MarkMissionsAsPaid, self).__init__()
        self.payment_info = payment_info

    def execute(self):

        for i in self.payment_info:
            exists, doc = missions_dao.get_if_exists(i["mission_id"])
            if exists:
                doc["reward_status"] = MissionRewardStatus.paid
                missions_dao.update_doc(i["mission_id"], doc)

        self.successful = True
        return "success"
