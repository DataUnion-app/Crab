import json
import os
from datetime import datetime
from enum import Enum

from commands.base_command import BaseCommand
from commands.metadata.add_new_image_command import AddNewImageCommand
from commands.metadata.upload_ipfs_command import UploadIpfsCommand
from config import config
from dao.metadata_dao import image_metadata_dao
from models.metadata.metadata_models import Source


class NcightEntityFileType(str, Enum):
    image = "image"
    user_metadata = "user_metadata"


class CreateNcightEntityCommand(BaseCommand):
    def __init__(self, public_address: str, file_path: str, file_type: NcightEntityFileType,
                 media_type: str, file_name: str, storage: str = None):
        super(CreateNcightEntityCommand, self).__init__(public_address)
        self.file_path = file_path
        self.file_type = file_type
        self.media_type = media_type
        self.source = Source.ncight
        self.original_file_name = file_name
        self.storage = storage

    def execute(self):
        doc_id = image_metadata_dao.generate_new_doc_id()

        if self.file_type == NcightEntityFileType.user_metadata:
            destination_path = None


            document = {
                "created_at": datetime.utcnow().isoformat(),
                "updated_at": datetime.utcnow().isoformat(),
                "created_by": self.public_address,
                "file_type": self.file_type,
                "source": self.source,
                "type": self.media_type,
                "available_for_annotation": True,
                "available_for_verification": True,
                "available_for_download": False,
                "original_file_name": self.original_file_name
            }

            with open(self.file_path, 'r') as f:
                json_content = json.load(f)
                document["type"] = "json"
                document["user_metadata"] = json_content

            if self.storage == "ipfs":
                c = UploadIpfsCommand(self.file_path)
                result = c.execute()
                if c.successful:
                    document["file_path"] = result["url"]
                    document["storage"] = self.storage
            elif self.storage == "filecoin":
                self.messages.append("Filecoin storage is retired")
                self.successful = False
                return

            if not document["file_path"]:
                filename = os.path.basename(self.file_path)
                upload_directory = os.path.join(config["application"]["upload_folder"], self.public_address)
                destination_path = os.path.join(upload_directory, doc_id + "-" + filename)
                os.rename(self.file_path, destination_path)
                document["file_path"] = destination_path
                document["storage"] = ""

            image_metadata_dao.save(doc_id, document)
            self.successful = True
            return doc_id
        elif self.file_type == NcightEntityFileType.image:
            c = AddNewImageCommand(public_address=self.public_address, image_path=self.file_path, storage=self.storage)
            result = c.execute()
            if c.successful is False:
                self.messages = c.messages
                self.successful = False
                return
            self.successful = True
            return result
