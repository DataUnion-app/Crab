from dao.metadata_dao import image_metadata_dao
from commands.base_command import BaseCommand
from datetime import datetime
import logging


class OverallStatsCommand(BaseCommand):
    def __init__(self, data_type: str):
        super().__init__()
        self.imageMetadataDao = image_metadata_dao
        self.data_type = data_type

    def execute(self):
        if not self.validate_input():
            self.successful = False
            return
        start_date = datetime.strptime(self.input["start_date"], "%d-%m-%Y")
        end_date = datetime.strptime(self.input["end_date"], "%d-%m-%Y")

        result = image_metadata_dao.get_overall_stats(self.data_type, start_date, end_date)
        self.successful = True
        return result

    @property
    def is_valid(self):
        pass

    def validate_input(self):
        try:
            start_date = datetime.strptime(self.input["start_date"], "%d-%m-%Y")
            end_date = datetime.strptime(self.input["end_date"], "%d-%m-%Y")
        except Exception as e:
            self.messages.append(
                "Unable to parse date. Expected input in dd-mm-yyyy format"
            )
            # logging.exception(e, exc_info=True)
            return False

        delta = end_date - start_date

        if delta.days < 0:
            self.messages.append("Invalid date range.")
            return False

        if delta.days > 366 * 3:
            self.successful = False
            self.messages.append(
                "Date range too large. Max difference allowed: 1098 days"
            )
            return False
        return True
