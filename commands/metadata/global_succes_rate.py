from commands.base_command import BaseCommand
from dao.metadata_dao import image_metadata_dao


class GlobalSuccessRate(BaseCommand):
    def __init__(self):
        super(GlobalSuccessRate, self).__init__()
        self.image_metadata_dao = image_metadata_dao

    def execute(self):

        result = self.image_metadata_dao.global_succes_rate(
        )
        self.successful = True
        return result

