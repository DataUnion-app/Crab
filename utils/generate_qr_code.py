import qrcode
import zipfile
from datetime import datetime
from PIL import Image
import os
from config import config
from dao.qrcode_dao import qrcode_dao
from dao.batch_dao import batch_dao
from models.metadata.metadata_models import Source, QRCodeStatus, QRCodeType
from utils.get_hash import get_hash
def generate_qr_code(public_address, product_id, batch_name, batch_size):
    batch_id = batch_dao.create_batch(public_address,product_id,batch_name,batch_size, None)
    image_file_paths = []
    for item_number in range(1, int(batch_size) + 1):
        dir_path = os.path.join(
                os.path.abspath(os.curdir),
                config["application"]["upload_folder"], "generated_qr_code"
            )
        if not os.path.exists(dir_path):
            os.makedirs(dir_path)
        # Construct the content string with product_name, batch_id, and counter
        content = f"{public_address}_{product_id}_{batch_id}_{batch_name}_{batch_size}_{item_number}"

        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_H,
            box_size=50,
            border=2,
        )
        qr.add_data(content)
        qr.make(fit=True)
        
        # Create a QR code image
        qr_img = qr.make_image(fill_color="black", back_color="white")
        # Save the QR code image
        qr_code_filename = f"{public_address}_{product_id}_{batch_id}_{batch_size}_{batch_name}_{batch_size}_{item_number}.png"
        filepath = os.path.join(dir_path, qr_code_filename)
        qr_img.save(filepath)
        image_file_paths.append(filepath)
        relative_filepath = os.path.join(
            config["application"]["upload_folder"], 
            "generated_qr_code", 
            qr_code_filename
        )
        hash_value = get_hash(content)
        qrcode_dao.create_new_qrcode(public_address, product_id, batch_id, content, hash_value, QRCodeStatus.created, False, QRCodeType.general, relative_filepath, Source.recyclium)
    
    zip_filename = f"qrcode_zip_{str(datetime.utcnow().timestamp()*1000)}.zip"
    zip_file_path = os.path.join(dir_path, zip_filename)
    # Create a new zip file
    with zipfile.ZipFile(zip_file_path, 'w') as zipf:
        # Add each image file to the zip file
        for image_file_path in image_file_paths:
            zipf.write(image_file_path, os.path.basename(image_file_path))
    relative_filepath = os.path.join(
        config["application"]["upload_folder"], 
        "generated_qr_code", 
        zip_filename
    )
    batch_dao.set_zip_filepath(batch_id, relative_filepath)
    return {
        "filepath": relative_filepath,
        "batch_id": batch_id
    }

