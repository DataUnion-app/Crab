from commands.base_command import BaseCommand
from dao.taxonomy_dao import taxonomy_dao
from datetime import datetime
import logging


class GetOverallStatsCommand(BaseCommand):
    def __init__(self):
        super(GetOverallStatsCommand, self).__init__()
        self.taxonomy_dao = taxonomy_dao

    def execute(self):

        if not self.validate_input():
            self.successful = False
            return
        start_date = datetime.strptime(self.input["start_date"], "%d-%m-%Y")
        end_date = datetime.strptime(self.input["end_date"], "%d-%m-%Y")

        result = taxonomy_dao.get_overall_swipe_stats(start_date, end_date)
        self.successful = True
        return result

    def validate_input(self):
        try:
            start_date = datetime.strptime(self.input["start_date"], "%d-%m-%Y")
            end_date = datetime.strptime(self.input["end_date"], "%d-%m-%Y")
        except Exception as e:
            self.messages.append(
                "Unable to parse date. Expected input in dd-mm-yyyy format"
            )
            logging.exception(e, exc_info=True)
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
