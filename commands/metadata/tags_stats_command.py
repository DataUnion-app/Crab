from dao.image_metadata_dao import image_metadata_dao
from commands.base_command import BaseCommand
import logging
import traceback


class TagStatsCommand(BaseCommand):

    def __init__(self):
        super().__init__()
        self.image_metadata_dao = image_metadata_dao

    def execute(self):
        result = None
        self.successful = False
        try:
            self.successful = True
            result = self.image_metadata_dao.get_tag_stats()
        except Exception as e:
            logging.error(traceback.format_exc())
        return result
