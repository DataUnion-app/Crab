from dao.image_metadata_dao import ImageMetadataDao
from commands.base_command import BaseCommand
from config import config
import logging
import traceback


class TagStatsCommand(BaseCommand):

    def __init__(self):
        super().__init__()
        user = config['couchdb']['user']
        password = config['couchdb']['password']
        db_host = config['couchdb']['db_host']
        metadata_db = config['couchdb']['metadata_db']
        self.image_metadata_dao = ImageMetadataDao()
        self.image_metadata_dao.set_config(user, password, db_host, metadata_db)

    def execute(self):
        result = None
        self.successful = False
        try:
            self.successful = True
            result = self.image_metadata_dao.get_tag_stats()
        except Exception as e:
            logging.error(traceback.format_exc())
        return result
