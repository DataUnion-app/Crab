from datetime import datetime

from dao.metadata_dao import image_metadata_dao
from commands.base_command import BaseCommand
import logging
import traceback


class TagStatsCommand(BaseCommand):
    def __init__(self, data_type: str):
        super().__init__()
        self.image_metadata_dao = image_metadata_dao
        self.data_type = data_type

    def execute(self):
        result = None
        self.successful = False
        try:
            self.successful = True
            start_date = datetime.strptime(self.input["start_date"], "%d-%m-%Y")
            end_date = datetime.strptime(self.input["end_date"], "%d-%m-%Y")
            result = self.image_metadata_dao.get_tag_stats(self.data_type, start_date, end_date)
        except Exception as e:
            self.successful = False
            logging.error(traceback.format_exc())
        return result
