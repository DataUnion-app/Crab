from dao.image_metadata_dao import ImageMetadataDao
from commands.base_command import BaseCommand
from config import config


class VerifyImageCommand(BaseCommand):

    def __init__(self):
        super().__init__()
        user = config['couchdb']['user']
        password = config['couchdb']['password']
        db_host = config['couchdb']['db_host']
        metadata_db = config['couchdb']['metadata_db']
        self.imageMetadataDao = ImageMetadataDao()
        self.imageMetadataDao.set_config(user, password, db_host, metadata_db)

    def execute(self):
        if not self.validate_input():
            self.successful = False
            self.messages.append('Invalid input.')
            return
        results = self.imageMetadataDao.mark_as_verified(self.input['data'], self.input['public_address'])

        for result in results:
            if result['success']:
                self.imageMetadataDao.move_to_verified_if_possible(result['image_id'])

        if all(result['success'] is True for result in results):
            self.successful = True
        else:
            self.messages.append('Some or all images are not in verifiable state')
            self.successful = False

    def validate_input(self):
        if not self.input:
            self.messages.append("Empty input body.")
            return False
        if not isinstance(self.input['data'], list):
            self.messages.append('"data" is not a list.')
            return False

        for row in self.input['data']:
            if not isinstance(row, dict):
                self.messages.append('row in data not an object.')
                return False
            if not row.get('image_id'):
                self.messages.append('missing "image_id" in data.')
                return False
            if not row.get('tags'):
                self.messages.append('missing "tags" in data.')
                return False
            if not isinstance(row['tags'].get('up_votes'), list):
                self.messages.append('"tags.up_votes" is not a list.')
                return False
            if not isinstance(row['tags'].get('down_votes'), list):
                self.messages.append('"tags.down_votes" is not a list.')
                return False
        return True

    @property
    def is_valid(self):
        pass
