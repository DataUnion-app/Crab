import os
from commands.base_command import BaseCommand
from dao.metadata_dao import image_metadata_dao

class DownloadVideoCommand(BaseCommand):
    def __init__(self, video_id):
        super().__init__()
        self.video_id = video_id
        self.image_metadata_dao = image_metadata_dao

    def execute(self):
        doc = image_metadata_dao.get_doc_by_id(self.video_id)

        if doc.get("error") == "not_found":
            self.successful = False
            self.messages.append("Metadata not found")
            return
        
        original_path = doc["video_path"]

        if os.path.isfile(original_path):
            self.successful = True
            return original_path
        
        self.successful = False
        self.messages.append("File not found")

