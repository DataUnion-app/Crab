from typing import List

from commands.base_command import BaseCommand
from commands.metadata.upload_ipfs_command import UploadIpfsCommand
from config import config
from dao.metadata_dao import image_metadata_dao
from PIL import Image
import os
from security.hashing import hash_image
from utils.get_random_string import get_random_string
from utils.get_project_dir import get_project_root
from dao.missions_dao import missions_dao
from commands.bounty.bounty_commands import UpdateBountyProgress


class AddNewImageCommand(BaseCommand):
    MIN_ALLOWED_HEIGHT = config["metadata"].getint("min_image_height")
    MIN_ALLOWED_WIDTH = config["metadata"].getint("min_image_width")

    VERIFICATION_MAX_IMAGE_WIDTH = config["metadata"].getint("verification_image_width")

    def __init__(self, public_address: str, image_path: str, bounty_name=["general"], use_hashing=True,
                 validate_dimensions=True, mission_id: str = None, storage: str = None):
        super().__init__()
        self.image_metadata_dao = image_metadata_dao
        self.use_hashing = use_hashing
        self.validate_dimensions = validate_dimensions
        self.bounty_name = bounty_name
        self.public_address = public_address
        self.image_path = image_path
        self.mission_id = mission_id
        self.storage = storage

    def execute(self):

        if not self.validate_input():
            self.successful = False
            return

        file_path = self.image_path

        if self.use_hashing:
            doc_id = str(hash_image(file_path))
        else:
            doc_id = get_random_string(15)

        image_exists = self.image_metadata_dao.exists(doc_id)
        if image_exists:
            self.messages.append("The uploaded file already exists in the dataset.")
            self.successful = False
            return doc_id

        with Image.open(file_path) as im:
            w, h = im.size

        destination_path = None
        if self.storage == "ipfs":
            c = UploadIpfsCommand(file_path)
            result = c.execute()
            if c.successful:
                destination_path = result["url"]
        elif self.storage == "filecoin":
            self.messages.append("Filecoin storage is retired")
            self.successful = False
            return

        if not destination_path:
            public_address = self.public_address
            image_dir = os.path.join(get_project_root(), config["application"]["upload_folder"], public_address)

            if not os.path.isdir(image_dir):
                os.makedirs(image_dir)

            filename = os.path.basename(file_path)
            destination_path = os.path.join(image_dir, doc_id + "-" + filename)
            os.rename(file_path, destination_path)
            relative_filepath = os.path.join(config["application"]["upload_folder"], public_address, doc_id + "-" + filename)


        # Save metadata
        self.image_metadata_dao.add_new_image_entity(doc_id, self.public_address, filename, relative_filepath, w, h,
                                                     self.bounty_name, self.storage)

        if self.mission_id is not None:
            missions_dao.update_progress(mission_id=self.mission_id, upload_ids=[doc_id])
            bounty_id = missions_dao.get_mission_details_by_id(mission_id=self.mission_id)['bounty_id']
            UpdateBountyProgress(bounty_id=bounty_id, entity_ids=[doc_id]).execute()

        self.successful = True
        return doc_id

    def validate_input(self):
        file_path = self.image_path
        with Image.open(file_path) as im:
            w, h = im.size

            if w < AddNewImageCommand.MIN_ALLOWED_WIDTH and self.validate_dimensions:
                self.messages.append(
                    f"Image width too small. Minimum allowed value [{AddNewImageCommand.MIN_ALLOWED_WIDTH}]"
                )
                return False

            if h < AddNewImageCommand.MIN_ALLOWED_HEIGHT and self.validate_dimensions:
                self.messages.append(
                    f"Image height too small. Minimum allowed value [{AddNewImageCommand.MIN_ALLOWED_HEIGHT}]"
                )
                self.successful = False
                return False

        return True
