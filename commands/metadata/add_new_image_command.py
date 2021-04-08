from datetime import datetime
from commands.base_command import BaseCommand
from config import config
from dao.image_metadata_dao import ImageMetadataDao
from models.ImageStatus import ImageStatus
from qrcode import make as make_qr
from PIL import Image
import os
from os.path import splitext
from security.hashing import hash_image


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
        image_dir = self.input['image_dir']

        qr_code_text = config['application']['qr_code_text']
        qr = make_qr(qr_code_text)
        qw, qh = qr.size

        image_path = os.path.join(image_dir, filename)
        im = Image.open(image_path)
        w, h = im.size

        if qw > w:
            qr = qr.resize((w, w))
        elif qh > h:
            qr = qr.resize((h, h))
        qw, qh = qr.size

        imd = im.load()
        for i in range(w):
            for j in range(h):
                d = imd[i, j]
                imd[i, j] = d[:-1] + ((d[-1] | 1) if qr.getpixel((i % qw, j % qh)) else (d[-1] & ~1),)

        root, ext = splitext(filename)
        qr_code_image_path = os.path.join(image_dir, root + '_watermark' + ext)
        im.save(qr_code_image_path)
        qr_code_hash = str(hash_image(qr_code_image_path))

        data_to_save = dict({})
        data_to_save["filename"] = filename
        data_to_save["uploaded_by"] = public_address
        data_to_save["status"] = "new"
        data_to_save["hash"] = doc_id
        data_to_save['qr_code_hash'] = qr_code_hash
        data_to_save["type"] = "image"
        data_to_save["extension"] = filename.split('.')[-1]
        data_to_save["status_description"] = ImageStatus.VERIFIABLE.name
        data_to_save["uploaded_at"] = datetime.timestamp(datetime.now())
        data_to_save["dimensions"] = [w, h]
        data_to_save["verified"] = []
        data_to_save["tag_data"] = []
        # Save metadata
        doc_id = self.image_metadata_dao.save(doc_id, data_to_save)["id"]

        self.successful = True
