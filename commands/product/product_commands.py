import logging

from commands.base_command import BaseCommand
from dao.product_dao import product_dao
from dao.bounty_dao import bounty_dao
from dao.entity_list_dao import entity_list_dao
from dao.qrcode_dao import qrcode_dao
from dao.metadata_dao import image_metadata_dao
from models.metadata.metadata_models import Source, QRCodeStatus
from commands.bounty.bounty_commands import HandleImagesOfBounty
from dao.report_dao import report_dao
from models.metadata.metadata_models import Source
from utils.generate_qr_code import generate_qr_code

class CreateProductCommand(BaseCommand):
    ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "PNG", "JPG", "JPEG", "GIF"}

    def __init__(self, public_address: str, name: str, material_type: str, material_size: int, example_image: str, source: Source = Source.default):
        super(CreateProductCommand, self).__init__(public_address)

        self.name = name
        self.material_type = material_type
        self.material_size = material_size
        self.example_image = example_image
        self.source = source

    def execute(self):
        if not self.validate_params():
            self.successful = False
            return

        product_id = product_dao.create_product(self.public_address, self.name, self.material_type, self.material_size,
                                              self.example_image, source=self.source)
        logging.info("Created new product [%s]", product_id)

        product = product_dao.get_product_by_id(product_id)

        self.successful = True
        return product

    def allowed_file(self, filename: str):
        return "." in filename and filename.rsplit(".", 1)[1].lower() in CreateProductCommand.ALLOWED_EXTENSIONS

    def validate_params(self):
        if len(self.name) < 2:
            self.messages.append("Product name should be up to 1 characters.")
        if not self.allowed_file(self.example_image):
            self.messages.append(f"Example image extension not allowed.")

        if self.messages:
            return False
        return True

class GetMyProducts(BaseCommand):
    def __init__(self, public_address: str):
        super(GetMyProducts, self).__init__(public_address)
        self.product_dao = product_dao

    def execute(self):
        result = self.product_dao.get_products_by_public_address(self.public_address)
        self.successful = True

        return result

class GetAllProducts(BaseCommand):
    def __init__(self):
        super(GetMyProducts, self).__init__()
        self.product_dao = product_dao

    def execute(self):
        result = self.product_dao.get_all_products()
        self.successful = True

        return result

class GetProductById(BaseCommand):
    def __init__(self, id: str):
        super(GetProductById, self).__init__()
        self.product_dao = product_dao
        self.id = id

    def execute(self):
        result = self.product_dao.get_product_by_id(self.id)
        self.successful = True

        return result

class CheckExistQRCode(BaseCommand):
    def __init__(self, public_address: str, qrcode: list, bounty_id: str):
        super(CheckExistQRCode, self).__init__()
        self.public_address = public_address
        self.bounty_dao = bounty_dao
        self.entity_list_dao = entity_list_dao
        self.qrcode = qrcode
        self.bounty_id = bounty_id
        self.qrcode_dao = qrcode_dao
        self.image_metadata_dao = image_metadata_dao

    def execute(self):
        if self.qrcode_dao.is_exist_qrcode(self.qrcode, self.bounty_id):
            self.successful = False
            self.messages.append('QRCode already exist')
            return False
        entity_list_id = self.bounty_dao.get_doc_by_id(self.bounty_id)["entity_list_id"]
        entity_list = self.entity_list_dao.get_doc_by_id(entity_list_id)
        accepted_entites = set(entity_list.get("accepted_image_ids", []))
        for entity_id in accepted_entites:
            entity_qrcode = self.image_metadata_dao.get_doc_by_id(entity_id).get("qr_code")
            if entity_qrcode == self.qrcode:
                self.successful = False
                self.messages.append('Already handed in bounty')
                return False
        all_entities = set(entity_list.get("entity_ids", []))
        for entity_id in all_entities:
            entity_qrcode = image_metadata_dao.get_doc_by_id(entity_id).get("qr_code")
            if entity_qrcode == self.qrcode:
                qrcode_id = self.qrcode_dao.create_qrcode(self.public_address, None, None, self.qrcode, self.bounty_id, Source.recyclium)
                accepted_image_ids = []
                rejected_image_ids = []
                accepted_image_ids.append(entity_id)
                image_handler_command = HandleImagesOfBounty(self.public_address,
                                                 self.bounty_id,
                                                 accepted_image_ids,
                                                 rejected_image_ids)
                result = image_handler_command.execute()

                if image_handler_command.successful:
                    self.qrcode_dao.update_status(self.qrcode, self.bounty_id, QRCodeStatus.scanned)
                self.successful = True
                return qrcode_id
        self.successful = False
        self.messages.append('No QRCode on the bounty items')
        return False
class GetMyReports(BaseCommand):
    def __init__(self, public_address: str, mission_id: str, sort_by: str, start_date: str, end_date: str):
        super(GetMyReports, self).__init__()
        self.report_dao = report_dao
        self.public_address = public_address
        self.mission_id = mission_id
        self.sort_by = sort_by
        self.start_date = start_date
        self.end_date = end_date

    def execute(self):
        result = self.report_dao.get_reports_by_filter(self.public_address, self.sort_by, self.mission_id, self.start_date, self.end_date)
        self.successful = True

        return result["result"]

class GenerateQRCode(BaseCommand):
    def __init__(self, public_address: str, product_id: str, batch_name: str, batch_size: int):
        super(GenerateQRCode, self).__init__()
        self.public_address = public_address
        self.batch_name = batch_name
        self.product_id = product_id
        self.batch_size = batch_size

    def execute(self):
        result = generate_qr_code(self.public_address, self.product_id, self.batch_name, self.batch_size)

        return {
            "batch_id": result.get("batch_id"),
            "filepath": result.get("filepath")
        }
