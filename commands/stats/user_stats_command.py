from dao.metadata_dao import image_metadata_dao
from commands.base_command import BaseCommand
from datetime import datetime


class UserStatsCommand(BaseCommand):
    def __init__(self, data_type: str):
        self.imageMetadataDao = image_metadata_dao
        self.data_type = data_type

    def execute(self):
        public_address = self.input["public_address"]
        start_date = datetime.strptime(self.input["start_date"], "%d-%m-%Y")
        end_date = datetime.strptime(self.input["end_date"], "%d-%m-%Y")

        result = image_metadata_dao.get_user_stats(self.data_type, public_address, start_date, end_date)
        self.successful = True
        return result

    @property
    def is_valid(self):
        pass
