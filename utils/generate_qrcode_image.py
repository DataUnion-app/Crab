import qrcode
from datetime import datetime
from PIL import Image
import os
from config import config

def generate_qrcode_image(content, hash):
    dir_path = os.path.join(
                os.path.abspath(os.curdir),
                config["application"]["upload_folder"], "aggregated_qrcodes"
            )
    if not os.path.exists(dir_path):
        os.makedirs(dir_path)

    qr = qrcode.QRCode(
            version=None,
            error_correction=qrcode.constants.ERROR_CORRECT_H,
            box_size=50,
            border=2,
        )
    qr.add_data(content)
    qr.make(fit=True)    
        
    qr_img = qr.make_image(fill_color="black", back_color="white")
    qr_code_filename = f"aggregated_qrcode_{hash}_{int(datetime.timestamp(datetime.utcnow()) * 1000)}.png"
    filepath = os.path.join(dir_path, qr_code_filename)
    qr_img.save(filepath)
    relative_filepath = os.path.join(
        config["application"]["upload_folder"], 
        "aggregated_qrcodes", 
        qr_code_filename
    )    
    return relative_filepath

