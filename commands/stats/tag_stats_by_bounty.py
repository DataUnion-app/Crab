from commands.base_command import BaseCommand
from dao.metadata_dao import image_metadata_dao


class GetTagStatsByBountyCommand(BaseCommand):

    def __init__(self, bounty_name: str):
        super().__init__()
        self.bounty_name = bounty_name
        self.image_metadata_dao = image_metadata_dao

    def execute(self):
        self.successful = True

        result = self.image_metadata_dao.get_tag_stats_by_bounty(self.bounty_name)

        return result
