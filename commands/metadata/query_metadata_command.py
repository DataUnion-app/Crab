from dao.image_metadata_dao import ImageMetadataDao
from commands.base_command import BaseCommand
from config import config


class QueryMetadataCommand(BaseCommand):

    def __init__(self):
        user = config['couchdb']['user']
        password = config['couchdb']['password']
        db_host = config['couchdb']['db_host']
        metadata_db = config['couchdb']['metadata_db']
        self.imageMetadataDao = ImageMetadataDao()
        self.imageMetadataDao.set_config(user, password, db_host, metadata_db)

    def execute(self):
        result = self.imageMetadataDao.query_metadata(self.input['status'], self.input['page'])
        return result

    @property
    def is_valid(self):
        pass
