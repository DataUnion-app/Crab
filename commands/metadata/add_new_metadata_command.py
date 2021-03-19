from dao.image_metadata_dao import ImageMetadataDao
from commands.base_command import BaseCommand
from config import config


class AddNewMetadataCommand(BaseCommand):

    def __init__(self):
        user = config['couchdb']['user']
        password = config['couchdb']['password']
        db_host = config['couchdb']['db_host']
        metadata_db = config['couchdb']['metadata_db']
        self.imageMetadataDao = ImageMetadataDao()
        self.imageMetadataDao.set_config(user, password, db_host, metadata_db)

    def execute(self):
        result = self.imageMetadataDao.add_metadata_for_image(self.input["public_address"], self.input["photo_id"],
                                                              self.input["tags"],
                                                              self.input.get("description", None))
        self.successful = True
        if result.get('ok') is True:
            return {"status": "success"}
        return {"status": "failed"}

    @property
    def is_valid(self):
        pass
