from commands.base_command import BaseCommand
from config import config
from dao.image_metadata_dao import ImageMetadataDao


class MyTagStatsCommand(BaseCommand):

    def __init__(self):
        super().__init__()
        user = config['couchdb']['user']
        password = config['couchdb']['password']
        db_host = config['couchdb']['db_host']
        metadata_db = config['couchdb']['metadata_db']
        self.imageMetadataDao = ImageMetadataDao()
        self.imageMetadataDao.set_config(user, password, db_host, metadata_db)

    def execute(self):
        if self.validate_input() is False:
            self.successful = False
            return

        result = self.imageMetadataDao.my_tags(self.input['public_address'])
        self.successful = True
        return result

    def validate_input(self):
        if self.input is None:
            self.messages.append("Empty input")
            return False

        if self.input.get('public_address') is None:
            self.messages.append("Missing public_address")
            return False

        return True
