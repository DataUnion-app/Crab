import os
import mimetypes

from PIL import Image

from commands.metadata.create_new_entity.create_brainstem_entity import CreateBrainStemEntityCommand, EntitySubType
from commands.metadata.create_new_entity.create_ncight_entity import CreateNcightEntityCommand, NcightEntityFileType
from config import config
from datetime import datetime

from models.metadata.metadata_models import Source
from security.hashing import hash_file
from models.ImageStatus import ImageStatus
from werkzeug.utils import secure_filename
from utils.get_random_string import get_random_string

from commands.base_command import BaseCommand
from commands.bounty.bounty_commands import UpdateBountyProgress
from commands.metadata.upload_ipfs_command import UploadIpfsCommand
from commands.dataunions.brainstem.consent import has_brainstem_data_consent

from dao.missions_dao import missions_dao
from dao.metadata_dao import image_metadata_dao
from dao.users_dao import user_dao

mimetypes.init()


class UploadMediaCommand(BaseCommand):
    MIN_ALLOWED_HEIGHT = config["metadata"].getint("min_image_height")
    MIN_ALLOWED_WIDTH = config["metadata"].getint("min_image_width")
    VERIFICATION_MAX_IMAGE_WIDTH = config["metadata"].getint("verification_image_width")

    allowed_media_type = ["audio", "video", "image", "text"]

    def __init__(self,
                 file,
                 uploaded_by: str,
                 bounty: list,
                 use_hashing=True,
                 validate_dimensions=True,
                 mission_id: str = "",
                 source: Source = None,
                 file_type: str = None,
                 storage: str = None,
                 qrcode_id: str = None):
        super().__init__()
        self.file = file
        if isinstance(self.file, str):
            self.media_type = "image"
        else:
            self.media_type = self.get_media_type(self.file.filename)
        self.uploaded_by = uploaded_by
        self.image_metadata_dao = image_metadata_dao
        self.bounty = bounty
        self.use_hashing = use_hashing
        self.validate_dimensions = validate_dimensions
        self.mission_id = mission_id
        self.w = 0
        self.h = 0
        self.source = source
        self.file_type = file_type
        self.storage = storage
        self.qrcode_id = qrcode_id
        self.error_status = 400

    def execute(self):
        if self.source == Source.brainstem:
            users = user_dao.get_by_public_address(self.uploaded_by).get("result", [])
            if len(users) != 1 or not has_brainstem_data_consent(users[0]):
                self.successful = False
                self.error_status = 403
                self.messages.append("Brainstem data consent is required")
                return None

        if isinstance(self.file, str):
            file_path = self.file
            filename = self.file.split('/')[-1]
        else:
            if not self.validate_file():
                self.successful = False
                return

            dir_path = os.path.join(
                os.path.abspath(os.curdir),
                config["application"]["upload_folder"],
                self.uploaded_by, "temp"
            )
            if not os.path.exists(dir_path):
                os.makedirs(dir_path)
            filename = secure_filename(self.file.filename)
            file_path = os.path.join(dir_path, filename)
            relative_filepath = os.path.join(
                os.path.abspath(os.curdir),
                config["application"]["upload_folder"],
                self.uploaded_by, "temp",
                filename
            )
            self.file.save(file_path)
        if self.source == Source.brainstem:

            if not self.file_type:
                self.successful = False
                self.messages.append(f"[{self.file_type}] Not a valid file type for [{self.source}]")

            result = None
            try:
                brainstem_file_type = EntitySubType[self.file_type]
                c = CreateBrainStemEntityCommand(self.uploaded_by, relative_filepath, brainstem_file_type, self.media_type,
                                                 filename, self.storage)
                result = c.execute()
                if c.successful:
                    self.successful = True
                else:
                    self.successful = False
            except Exception as e:
                self.successful = False
                self.messages.append(str(e))
            finally:
                if os.path.isfile(file_path):
                    os.remove(file_path)
                return result
        elif self.source == Source.ncight:
            ncight_file_type = NcightEntityFileType[self.file_type]
            c = CreateNcightEntityCommand(self.uploaded_by, relative_filepath, ncight_file_type, self.media_type, filename, self.storage)
            result = c.execute()
            if c.successful:
                self.successful = True
                return result
            else:
                self.messages = c.messages
                self.successful = False
        else:
            if not self.media_type:
                self.messages.append("The file extension is not supported.")
                return False

            if self.media_type == "image":
                dimension_validation = True

                try:
                    with Image.open(file_path) as im:
                        w, h = im.size

                        if self.validate_dimensions:
                            if w < self.MIN_ALLOWED_WIDTH:
                                self.messages.append(
                                    f"Image width too small. Minimum allowed value [{self.MIN_ALLOWED_WIDTH}]"
                                )
                                dimension_validation = False
                            if h < self.MIN_ALLOWED_HEIGHT:
                                self.messages.append(
                                    f"Image height too small. Minimum allowed value [{self.MIN_ALLOWED_HEIGHT}]"
                                )
                                dimension_validation = False

                        self.w = w
                        self.h = h
                except Exception as err:
                    self.messages.append("Failed to open the image file")
                    dimension_validation = False

                if not dimension_validation:
                    self.successful = False
                    os.remove(file_path)
                    return

            if self.use_hashing:
                doc_id = hash_file(file_path)
            else:
                doc_id = get_random_string(15)

            if self.image_metadata_dao.exists(doc_id):
                self.messages.append("The uploaded file already exists in the dataset.")
                os.remove(file_path)
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
                media_dir = os.path.join(config["application"]["upload_folder"], self.uploaded_by)

                if not os.path.isdir(media_dir):
                    os.makedirs(media_dir)

                filename = os.path.basename(file_path)
                destination_path = os.path.join(media_dir, doc_id + "-" + filename)
                os.rename(file_path, destination_path)

            self.image_metadata_dao.add_new_media_entity(doc_id,
                                                         self.media_type,
                                                         self.uploaded_by,
                                                         filename,
                                                         destination_path,
                                                         self.bounty,
                                                         self.w,
                                                         self.h,
                                                         self.source,
                                                         self.storage,
                                                         self.qrcode_id)

            if self.mission_id:
                missions_dao.update_progress(mission_id=self.mission_id,
                                             upload_ids=[doc_id])
                bounty_id = missions_dao.get_mission_details_by_id(mission_id=self.mission_id)['bounty_id']
                image_metadata_dao.update_mission_bounty_id(doc_id, bounty_id, self.mission_id)
                UpdateBountyProgress(bounty_id=bounty_id, entity_ids=[doc_id]).execute()

            self.successful = True
            return doc_id

    def get_media_type(self, file_name):
        mimestart = mimetypes.guess_type(file_name)[0]

        if mimestart != None:
            mimestart = mimestart.split("/")[0]

            if mimestart in self.allowed_media_type:
                return mimestart

        return ""

    def validate_file(self):
        if not self.file or not self.file.filename:
            self.messages.append("File not found.")
            return False

        return True
