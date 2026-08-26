import os, logging

from commands.base_command import BaseCommand
from config import config
from dao.qrcode_dao import qrcode_dao
from dao.bounty_dao import bounty_dao
from dao.missions_dao import missions_dao
from dao.product_dao import product_dao
from dao.report_dao import report_dao
from dao.metadata_dao import image_metadata_dao
from dao.entity_list_dao import entity_list_dao
from models.metadata.metadata_models import Source, QRCodeStatus, ReportType, QRCodeType
from models.bounty import BountyStatus

from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
import qrcode
import csv
from datetime import datetime
from utils.generate_qrcode_image import generate_qrcode_image
from models.entity_list_models import EntityListType
from models.metadata.metadata_models import EntityType, Source
class SetQRCodeStorerToCreator(BaseCommand):
    def __init__(self, public_address:str, bounty_id: str):
        super(SetQRCodeStorerToCreator, self).__init__()
        self.qrcode_dao = qrcode_dao
        self.bounty_dao = bounty_dao
        self.bounty_id = bounty_id
        self.public_address = public_address

    def execute(self):
        qrcodes = self.qrcode_dao.get_qrcodes_by_bounty_id(self.bounty_id)["result"]
        for qrcode in qrcodes:
            qrcode_id = qrcode.get("_id")
            if qrcode.get("status") != QRCodeStatus.stored:
                self.successful = False
                self.messages.append(f"All status are not 'stored' [{qrcode_id}].")
                return False        
        
        bounty = self.bounty_dao.get_doc_by_id(self.bounty_id)
        bounty['status'] = BountyStatus.COMPLETED
        bounty_dao.update_doc(self.bounty_id, bounty)

        for qrcode in qrcodes:
            self.qrcode_dao.set_status(self.public_address, qrcode.get("_id"), QRCodeStatus.returned)
        self.successful = True
        return True

class ReportPDFCreation(BaseCommand):
    def __init__(self, public_address:str, mission_id: str, product_id: str, batch_name: str, start_date: str, end_date: str):
        super(ReportPDFCreation, self).__init__()
        self.qrcode_dao = qrcode_dao
        self.bounty_dao = bounty_dao
        self.product_dao = product_dao
        self.missions_dao = missions_dao
        self.report_dao = report_dao
        self.mission_id = mission_id
        self.product_id = product_id
        self.batch_name = batch_name
        self.start_date = start_date
        self.end_date = end_date
        self.public_address = public_address

    def execute(self):
        try:
            bounty_id = None
            if self.mission_id:
                bounty_id = self.missions_dao.get_doc_by_id(self.mission_id).get("bounty_id")
            qrcodes = self.qrcode_dao.get_qrcodes_by_bounty_id_start_end_date(
                bounty_id, self.product_id, self.batch_name, self.start_date, self.end_date)["result"]
            
            logo_path = config["qrcode"]["logo_path"]

            # Create a PDF document
            UPLOAD_FOLDER = 'pdf'
            dir_path = os.path.join(
                        os.path.abspath(os.curdir),
                        config["application"]["upload_folder"],
                        UPLOAD_FOLDER, self.public_address
                    )
            if not os.path.exists(dir_path):
                    os.makedirs(dir_path)
            
            filename = "report.pdf"
            if bounty_id is None:
                bounty_id = ""
            if self.product_id is None:
                product_id = ""
            filename = bounty_id + "_" + self.product_id + "_" + self.start_date + "_Report" + ".pdf"
            pdf_path = os.path.join(dir_path, filename)
            relative_filepath = os.path.join(
                        config["application"]["upload_folder"],
                        UPLOAD_FOLDER, self.public_address, filename
                    )
            document = SimpleDocTemplate(pdf_path, pagesize=letter)

            # Create a list to store the PDF elements
            elements = []

            # Add the logo image to the PDF in the right top corner
            logo = Image(logo_path, width=2*inch, height=1*inch)
            logo.drawHeight = 1*inch
            logo.drawWidth = 2*inch
            logo.wrapOn(document, document.width, document.height)
            elements.append(logo)

            # Add a title and text to the PDF
            styles = getSampleStyleSheet()
            title = Paragraph(bounty_id + "_" + self.product_id + "_" + self.start_date + "_Report", styles["Title"])
            elements.extend([title, Spacer(1, 0.2*inch)])

            for qrcode in qrcodes:
                # Add a QR code to the PDF
                qr_code = qrcode.get("qr_code")
                qr_code_image = Image(qrcode.get("filepath"), width=1.5*inch, height=1.5*inch)
                elements.append(qr_code_image)
                
                # Add text in the middle
                list_style = getSampleStyleSheet()["Title"]
                for value in qr_code:
                    value_element = Paragraph(value, list_style)
                    elements.append(value_element)
                
                # Create a table with data
                data = []

                status = qrcode.get("status")
                updated_at = qrcode.get("updated_at")
                uploaded_by = qrcode.get("uploaded_by")
                data.append(["status","updated_at","public_address"])
                data.append([status, updated_at, uploaded_by])
                table = Table(data, colWidths=[1*inch, 3*inch, 4*inch])
                style = TableStyle([
                    ('BACKGROUND', (0, 0), (-1, 0), colors.white),
                    ('TEXTCOLOR', (0, 0), (-1, 0), colors.black),
                    ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                    ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                    ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
                    ('BACKGROUND', (0, 1), (-1, -1), colors.white),
                    ('GRID', (0, 0), (-1, -1), 1, colors.black)
                    ])

                table.setStyle(style)

                elements.append(table)

            # Build the PDF report
            document.build(elements)
            
            file_stats = os.stat(pdf_path)
            
            file_size = file_stats.st_size / 1024
            
            report_id = self.report_dao.create_report(self.public_address, filename, relative_filepath, file_size, ReportType.pdf, self.mission_id, Source.recyclium)
            self.successful = True
            return report_id
        except Exception as e:
            self.successful = False
            self.messages.append(str(e))
            return False
        
class ReportCSVCreation(BaseCommand):
    def __init__(self, public_address:str, mission_id: str, product_id: str, batch_name: str, start_date: str, end_date: str):
        super(ReportCSVCreation, self).__init__()
        self.qrcode_dao = qrcode_dao
        self.bounty_dao = bounty_dao
        self.product_dao = product_dao
        self.missions_dao = missions_dao
        self.report_dao = report_dao
        self.mission_id = mission_id
        self.product_id = product_id
        self.batch_name = batch_name
        self.start_date = start_date
        self.end_date = end_date
        self.public_address = public_address

    def execute(self):
        try:
            bounty_id = None
            if self.mission_id:
                bounty_id = self.missions_dao.get_doc_by_id(self.mission_id).get("bounty_id")
            qrcodes = self.qrcode_dao.get_qrcodes_by_bounty_id_start_end_date(
                bounty_id, self.product_id, self.batch_name, self.start_date, self.end_date)["result"]
            
            UPLOAD_CSV_FOLDER = 'csv'
            dir_csv_path = os.path.join(
                        os.path.abspath(os.curdir),
                        config["application"]["upload_folder"],
                        UPLOAD_CSV_FOLDER, self.public_address
                    )
            if not os.path.exists(dir_csv_path):
                    os.makedirs(dir_csv_path)
            
            csv_filename = "report.csv"

            if bounty_id is None:
                bounty_id = ""
            if self.product_id is None:
                product_id = ""
            
            csv_filename = bounty_id + "_" + self.product_id + "_" + self.start_date + "_Report" + ".csv"
            csv_path = os.path.join(dir_csv_path, csv_filename)
            relative_filepath = os.path.join(
                        config["application"]["upload_folder"],
                        UPLOAD_CSV_FOLDER, self.public_address, csv_filename
                    )
            csv_list = [["qrcode", "status","updated_at","public_address"]]
            for qrcode in qrcodes:
                qr_code = qrcode.get("qr_code")
                data = []

                status = qrcode.get("status")
                updated_at = qrcode.get("updated_at")
                uploaded_by = qrcode.get("uploaded_by")

                csv_list.append([qr_code, status, updated_at, uploaded_by])
                
            
            with open(csv_path, mode='w', newline='') as file:
                writer = csv.writer(file)
                writer.writerows(csv_list)

            file_stats = os.stat(csv_path)
            
            file_size = file_stats.st_size / 1024
            
            
            report_id = self.report_dao.create_report(self.public_address, csv_filename, relative_filepath, file_size, ReportType.csv, self.mission_id, Source.recyclium)
            self.successful = True
            return report_id
        except Exception as e:
            self.successful = False
            self.messages.append(str(e))
            return False

class GetQRCodebyBountyID(BaseCommand):
    def __init__(self, bounty_id : str):
        super(GetQRCodebyBountyID, self).__init__()
        self.qrcode_dao = qrcode_dao
        self.bounty_id = bounty_id

    def execute(self):
        try:
            scanned_qrcodes = self.qrcode_dao.get_qrcodes_by_bounty_id_status(self.bounty_id, QRCodeStatus.scanned)
            stored_qrcodes = self.qrcode_dao.get_qrcodes_by_bounty_id_status(self.bounty_id, QRCodeStatus.stored)
            returned_qrcodes = self.qrcode_dao.get_qrcodes_by_bounty_id_status(self.bounty_id, QRCodeStatus.returned)
            doc = {}
            doc["scanned_qrcodes"] = scanned_qrcodes
            doc["stored_qrcodes"] = stored_qrcodes
            doc["returned_qrcodes"] = returned_qrcodes
            doc["scanned_count"] = len(scanned_qrcodes)
            doc["stored_count"] = len(stored_qrcodes)
            doc["returned_count"] = len(returned_qrcodes)
            
            self.successful = True
            return doc
        except Exception as e:
            self.successful = False
            self.messages.append(str(e))
            return False

class SetRewardbyQRCodeStatus(BaseCommand):
    def __init__(self, public_address: str, bounty_id: str, image_id: str, qrcode_status: QRCodeStatus, qrcode):
        super(SetRewardbyQRCodeStatus, self).__init__()
        self.qrcode_dao = qrcode_dao
        self.bounty_dao = bounty_dao
        self.image_metadata_dao = image_metadata_dao
        self.bounty_id = bounty_id
        self.public_address = public_address
        self.image_id = image_id
        self.qrcode_status = qrcode_status
        self.qrcode = qrcode

    def execute(self):
        bounty = self.bounty_dao.get_doc_by_id(self.bounty_id)
        rewards_allocated = bounty["rewards_allocated"]
        collector_address = self.image_metadata_dao.get_doc_by_id(self.image_id).get("uploaded_by")
        storer_address = self.public_address

        if self.qrcode_status == QRCodeStatus.scanned:
            collector_reward = rewards_allocated / 10 * 3
            storer_reward = rewards_allocated / 10

        if self.qrcode_status == QRCodeStatus.stored:
            collector_reward = rewards_allocated / 10 * 2
            storer_reward = rewards_allocated / 10 * 4

        if collector_reward:
            c = ClaimRewardByQRCodeCommand(collector_address, Source.recyclium, EntityType.image, collector_reward)
            result = c.execute()
            if not c.successful:
                self.successful = False
                return c.messages
            else:
                self.qrcode_dao.set_transfer_status_by_qrcode(self.public_address, self.qrcode, self.bounty_id, EntityRewardStatus.paid)
                
        if storer_reward:
            c = ClaimRewardByQRCodeCommand(storer_address, Source.recyclium, EntityType.image, storer_reward)
            result = c.execute()
            if not c.successful:
                self.successful = False
                return c.messages
            else:
                self.qrcode_dao.set_transfer_status_by_qrcode(self.public_address, self.qrcode, self.bounty_id, EntityRewardStatus.paid)
        self.successful = True
        return True

class CreateAggreggatedQRCode(BaseCommand):
    def __init__(self, public_address : str, qrcodes : list):
        super(CreateAggreggatedQRCode, self).__init__()
        self.qrcode_dao = qrcode_dao
        self.public_address = public_address
        self.qrcodes = qrcodes
        self.created_at = datetime.utcnow().replace(microsecond=0).isoformat()

    def execute(self):
        try:
            for qrcode in self.qrcodes:
                if not qrcode_dao.get_doc_by_id(qrcode):
                    return {
                        "success" : False,
                        "message" : "This " + qrcode + " doesn't exist in db so can't create aggregated QR code."
                    }
            aggregated_qrcode_content = self.public_address + "_" + self.created_at
            entity_ids = []
            for qrcode in self.qrcodes:
                aggregated_qrcode_content += "_" + qrcode
                metadata = image_metadata_dao.get_metadata_by_qrcode_id(qrcode)
                if len(metadata) > 0:
                    entity_ids.append(metadata[0].get("_id"))
                else:
                    return {
                        "success" : False,
                        "message" : "Metadata for this " + qrcode + " doesn't exist in db so can't create aggregated QR code."
                    }
            hash_object = hashlib.sha256(aggregated_qrcode_content.encode())
            hash_value = hash_object.hexdigest()
            aggregated_qrcode_filepath = generate_qrcode_image(aggregated_qrcode_content, hash_value)   
            qrcode_id = qrcode_dao.create_new_qrcode(
                self.public_address,
                None, None, aggregated_qrcode_content, hash_value, QRCodeStatus.scanned, False, QRCodeType.aggregated,
                aggregated_qrcode_filepath, Source.recyclium
            )
            
            entity_list_id = entity_list_dao.create_new_list(
                self.public_address, EntityType.image, entity_ids, EntityListType.BOUNTY, aggregated_qrcode_filepath, qrcode_id,
                Source.default
            )
            
            return {
                        "success" : True,
                        "message" : "Aggregated QR code is created successfully.",
                        "data" : {
                            "entity_list_id": entity_list_id,
                            "filepath": aggregated_qrcode_filepath
                        }
                    }
        except Exception as e:
            self.successful = False
            self.messages.append(str(e))
            return False

class GetScannedQRCodebyBountyID(BaseCommand):
    def __init__(self, public_address: str, bounty_id : str):
        super(GetScannedQRCodebyBountyID, self).__init__(public_address)
        self.qrcode_dao = qrcode_dao
        self.bounty_id = bounty_id

    def execute(self):
        try:
            bounty = bounty_dao.get_doc_by_id(self.bounty_id)
            scanned_qrcodes = self.qrcode_dao.get_scanned_qrcodes_by_collector(self.public_address, bounty['product_id'], bounty['batch_ids'])
            self.successful = True
            return scanned_qrcodes
        except Exception as e:
            self.successful = False
            self.messages.append(str(e))
            return False
