import os
from PIL import Image
from commands.base_command import BaseCommand
from config import config
from qrcode import make as make_qr
from dao.metadata_dao import image_metadata_dao
from os.path import splitext
import logging


class GetImageForVerification(BaseCommand):
    VERIFICATION_MAX_IMAGE_WIDTH = config["metadata"].getint("verification_image_width")

    def __init__(self, image_id):
        super().__init__()
        self.image_metadata_dao = image_metadata_dao
        self.image_id = image_id

    def execute(self):
        dir = config["metadata"]["verification_images_directory"]

        document = image_metadata_dao.get_doc_by_id(self.image_id)
        if document.get("error") == "not_found":
            self.successful = False
            self.messages.append("Metadata not found")
            return

        original_image_path = document["image_path"]
        ext = splitext(document["filename"])[1]
        image_path = os.path.join(dir, self.image_id + ext)

        self.successful = True
        if os.path.isfile(image_path):
            return image_path

        return GetImageForVerification.generate_image_for_verification(
            original_image_path, image_path
        )

    @staticmethod
    def generate_image_for_verification(original_image_path, target_path):

        im = Image.open(original_image_path)
        w, h = im.size

        verification_image_w = min(
            GetImageForVerification.VERIFICATION_MAX_IMAGE_WIDTH, w
        )
        w_percent = verification_image_w / float(w)
        h_size = int((float(h) * float(w_percent)))
        im = im.resize((verification_image_w, h_size), Image.ANTIALIAS)

        qr_code_text = config["application"]["qr_code_text"]
        qr = make_qr(qr_code_text)
        qw, qh = qr.size

        if qw > verification_image_w:
            qr = qr.resize((verification_image_w, verification_image_w))
        elif qh > h_size:
            qr = qr.resize((h_size, h_size))
        qw, qh = qr.size

        imd = im.load()
        try:
            for i in range(verification_image_w):
                for j in range(h_size):
                    d = imd[i, j]
                    imd[i, j] = d[:-1] + (
                        (d[-1] | 1) if qr.getpixel((i % qw, j % qh)) else (d[-1] & ~1),
                    )
        except TypeError as e:
            logging.exception(e, exc_info=True)

        finally:
            im.save(target_path)
            return target_path
