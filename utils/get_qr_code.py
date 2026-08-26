import os
from config import config
import zbarlight
from werkzeug.utils import secure_filename
from PIL import Image

ALLOWED_EXTENSIONS = {'jpg', 'jpeg', 'png', 'gif'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def get_filepath(uploaded_file, upload_folder, public_address):
    dir_path = os.path.join(
                os.path.abspath(os.curdir),
                config["application"]["upload_folder"],
                public_address, upload_folder
            )
    if not os.path.exists(dir_path):
            os.makedirs(dir_path)
    if uploaded_file and allowed_file(uploaded_file.filename):
        filename = secure_filename(uploaded_file.filename)
        filepath = os.path.join(dir_path, filename)
        uploaded_file.save(filepath)
    return filepath

def get_qr_code(filepath):
    with open(filepath, 'rb') as image_file:
        image = Image.open(filepath)
        image.load()
    qr_codes = zbarlight.scan_codes(['qrcode'], image)
    qr_codes = [x.decode('utf-8') for x in qr_codes]
    return qr_codes