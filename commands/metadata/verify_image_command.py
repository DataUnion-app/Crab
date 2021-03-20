from dao.image_metadata_dao import ImageMetadataDao
from commands.base_command import BaseCommand
from config import config


class VerifyImageCommand(BaseCommand):

    def __init__(self):
        user = config['couchdb']['user']
        password = config['couchdb']['password']
        db_host = config['couchdb']['db_host']
        metadata_db = config['couchdb']['metadata_db']
        self.imageMetadataDao = ImageMetadataDao()
        self.imageMetadataDao.set_config(user, password, db_host, metadata_db)

    def execute(self):
        result = self.imageMetadataDao.mark_as_verified(self.input['photos'], self.input['public_address'])
        if result:
            self.successful = True
        else:
            self.successful = False

    @property
    def is_valid(self):
        pass
