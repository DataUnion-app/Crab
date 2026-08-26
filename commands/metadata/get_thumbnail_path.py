from commands.base_command import BaseCommand
from dao.metadata_dao import image_metadata_dao
import os
from PIL import Image
import logging
from config import config


class GetThumbnailPath(BaseCommand):
    THUMBNAIL_DIRECTORY = config["metadata"]["thumbnail_directory"]
    THUMBNAIL_WIDTH = config["metadata"].getfloat("thumbnail_width")
    THUMBNAIL_HEIGHT = config["metadata"].getfloat("thumbnail_height")
    THUMBNAIL_EXTENSION = "png"

    def __init__(self):
        super(GetThumbnailPath, self).__init__()
        self.image_metadata_dao = image_metadata_dao
        self.scale_factor = 0.1

    def execute(self):
        if not self.validate_input():
            self.successful = False
            return
        image_id = self.input["image_id"]
        exists = self.image_metadata_dao.exists(image_id)
        if not exists:
            self.messages.append("Image id not found")
            self.successful = False
            return

        metadata_doc = self.image_metadata_dao.get_doc_by_id(image_id)
        image_path = metadata_doc["image_path"]
        x_size, y_size = metadata_doc["dimensions"]

        outfile = os.path.join(
            GetThumbnailPath.THUMBNAIL_DIRECTORY,
            image_id + "." + GetThumbnailPath.THUMBNAIL_EXTENSION,
        )
        if os.path.isfile(outfile):
            self.successful = True
            return outfile

        if image_path != outfile:
            try:
                im = Image.open(image_path)
                size = (
                    GetThumbnailPath.THUMBNAIL_WIDTH,
                    GetThumbnailPath.THUMBNAIL_HEIGHT,
                )
                im.thumbnail(size=size)
                im.save(outfile, GetThumbnailPath.THUMBNAIL_EXTENSION)
            except IOError as e:
                logging.exception(e)
                self.successful = False
                self.messages.append("Could not create thumbnail for image")
                return
        self.successful = True
        return outfile

    def validate_input(self):
        if not self.input:
            self.messages.append("Empty input")
            return False

        if not isinstance(self.input.get("image_id"), str):
            self.messages.append("'image_id' is not a string")
            return False

        return True
