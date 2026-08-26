from commands.base_command import BaseCommand
from dao.metadata_dao import image_metadata_dao


class SuccessRate(BaseCommand):
    def __init__(self):
        super(SuccessRate, self).__init__()
        self.image_metadata_dao = image_metadata_dao

    def execute(self):

        result = self.image_metadata_dao.succes_rate(
            self.input["public_address"]
        )
        self.successful = True
        return result

