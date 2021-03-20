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

        is_valid = self.validate_input()

        if is_valid is False:
            self.successful = False
            return

        result = self.imageMetadataDao.query_metadata(self.input['status'], self.input['page'])
        self.successful = True
        return result

    def validate_input(self):
        if self.input is None:
            self.messages.append("Empty input")
            return

        if self.input.get('status') is None:
            self.messages.append("Missing status")
            return False

        if self.input.get('page') is None:
            self.messages.append("Missing page")
            return False

        if self.input.get('skip_untagged') is None:
            self.messages.append("Missing skip_untagged")
            return False

    @property
    def is_valid(self):
        pass
