import os
import glob
from config import config
from dao.metadata_dao import image_metadata_dao
from commands.base_command import BaseCommand

class GetMetadataFileCommand(BaseCommand):

    def __init__(self, entity_type: str, doc_id: str, name: str):
        super().__init__()
        self.image_metadata_dao = image_metadata_dao
        self.entity_type = entity_type
        self.doc_id = doc_id
        self.name = name

    def execute(self):
        self.successful = True
        metadata = image_metadata_dao.get_doc_by_id(self.doc_id)
        if metadata["storage"] == "ipfs" and metadata["file_path"]:
            return metadata["file_path"]

        uploaded_by = metadata["uploaded_by"]

        file_path = os.path.join(
                        os.path.abspath(os.curdir),
                        config["application"]["upload_folder"],
                        uploaded_by,
                        self.entity_type,
                        self.doc_id,
                        self.name
                    )

        if len(glob.glob(file_path)) > 0:
            return file_path
        else:
            self.successful = False
            self.messages.append("File not found")
            return False
