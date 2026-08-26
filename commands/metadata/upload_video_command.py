from datetime import datetime
import os
from werkzeug.utils import secure_filename
from config import config

from commands.base_command import BaseCommand
from commands.metadata.upload_ipfs_command import UploadIpfsCommand
from dao.metadata_dao import image_metadata_dao
from models.ImageStatus import ImageStatus
from utils.get_random_string import get_random_string


class UploadVideoCommand(BaseCommand):
    allowed_mime_types = ['video/mp4', 'video/ogg', 'video/webm', 'video/3gp', 'video/m4a', 'video/mkv', 'video/amr',
                          'image/gif', "video/x-matroska"]
    allowed_extensions = ['mp4', '3gp', 'mkv', 'm4a', 'amr', 'ogg', 'gif']

    def __init__(self, file, uploaded_by: str, bounty: str, storage: str = None):
        super().__init__()
        self.file = file
        self.uploaded_by = uploaded_by
        self.image_metadata_dao = image_metadata_dao
        self.bounty = bounty
        self.storage = storage

    def execute(self):
        if not self.validate_file():
            self.successful = False
            return

        file = self.file
        dir_path = os.path.join(
            os.path.abspath(os.curdir),
            config["application"]["upload_folder"],
            self.uploaded_by, "temp"
        )
        if not os.path.exists(dir_path):
            os.makedirs(dir_path)
        filename = secure_filename(file.filename)
        file_path = os.path.join(dir_path, filename)
        file.save(file_path)

        public_address = self.uploaded_by

        doc_id = get_random_string(10)

        if self.image_metadata_dao.exists(doc_id):
            self.messages.append("The uploaded file already exists in the dataset.")
            self.successful = False
            return

        destination_path = None
        if self.storage == "ipfs":
            c = UploadIpfsCommand(file_path)
            result = c.execute()
            if c.successful:
                destination_path = result["url"]
        elif self.storage == "filecoin":
            self.messages.append("Filecoin storage is retired")
            self.successful = False
            os.remove(file_path)
            return

        if not destination_path:
            video_dir = os.path.join(config["application"]["upload_folder"], public_address)

            filename = os.path.basename(file_path)
            destination_path = os.path.join(video_dir, doc_id + "-" + filename)
            os.rename(file_path, destination_path)

        self.image_metadata_dao.add_new_video_entity(doc_id, self.uploaded_by, filename, destination_path, self.bounty, self.storage)
        self.successful = True

        return doc_id

    def file_allowed(self):
        filename = self.file.filename
        return "." in filename and filename.rsplit(".", 1)[
            1].lower() in self.allowed_extensions

    def validate_mimetype(self):
        content_type = self.file.content_type
        return content_type in self.allowed_mime_types

    def validate_file(self):
        if not self.file or not self.file.filename:
            return False
        if not self.file_allowed():
            self.messages.append("File extension not supported.")
            return False
        if not self.validate_mimetype():
            self.messages.append(f"mime-type [{self.file.content_type}] not supported")
            return False
        return True
