from datetime import datetime
from commands.base_command import BaseCommand
from config import config
from dao.image_metadata_dao import ImageMetadataDao
from models.ImageStatus import ImageStatus


class AddNewImageCommand(BaseCommand):
    def __init__(self):
        super().__init__()
        user = config['couchdb']['user']
        password = config['couchdb']['password']
        db_host = config['couchdb']['db_host']
        metadata_db = config['couchdb']['metadata_db']
        self.image_metadata_dao = ImageMetadataDao()
        self.image_metadata_dao.set_config(user, password, db_host, metadata_db)

    def execute(self):
        doc_id = self.input['doc_id']
        filename = self.input['filename']
        public_address = self.input['public_address']

        data_to_save = dict({})
        data_to_save["filename"] = doc_id + '-' + filename
        data_to_save["uploaded_by"] = public_address
        data_to_save["status"] = "new"
        data_to_save["hash"] = doc_id
        data_to_save["type"] = "image"
        data_to_save["extension"] = filename.split('.')[-1]
        data_to_save["status_description"] = ImageStatus.AVAILABLE_FOR_TAGGING.name
        data_to_save["uploaded_at"] = datetime.timestamp(datetime.now())

        # Save metadata
        doc_id = self.image_metadata_dao.save(doc_id, data_to_save)["id"]

        self.successful = True
