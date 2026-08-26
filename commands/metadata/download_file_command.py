import os
import requests
from commands.base_command import BaseCommand
from dao.metadata_dao import image_metadata_dao

class DownloadFileCommand(BaseCommand):
    def __init__(self, public_address: str, metadata_id):
        super().__init__(public_address=public_address)
        self.metadata_id = metadata_id
        self.image_metadata_dao = image_metadata_dao

    def execute(self):
        doc = image_metadata_dao.get_doc_by_id(self.metadata_id)

        if doc.get("error") == "not_found":
            self.successful = False
            self.messages.append("Metadata not found")
            return

        uploader = None
        if "uploaded_by" in doc:
            uploader = doc["uploaded_by"]
        else:
            uploader = doc["created_by"]

        if uploader != self.public_address:
            self.successful = False
            self.messages.append("You don't have enough permission to download the file")
            return
        
        file_path = None
        if doc["type"] == "image":
            file_path = doc["image_path"]
        elif doc["type"] == "video":
            file_path = doc["video_path"]
        elif "audio_path" in doc:
            file_path = doc["audio_path"]
        elif "file_path" in doc:
            file_path = doc["file_path"]

        if file_path is None:
            self.successful = False
            self.messages.append("Metadata not found")
            return

        filename = None
        if "filename" in doc:
            filename = doc["filename"]
        else:
            filename = doc["original_file_name"]

        content = None
        if "storage" in doc:
            if doc["storage"] == "ipfs":
                response = requests.get(file_path)
                content = response.content
            elif doc["storage"] == "filecoin":
                self.successful = False
                self.messages.append("Filecoin storage is retired")
                return

        if content is None:
            if os.path.isfile(file_path):
                self.successful = True
                with open(file_path, 'rb') as f:
                    content = f.read()
        
        self.successful = True
        return {
            "filename": filename,
            "content": content
        }
