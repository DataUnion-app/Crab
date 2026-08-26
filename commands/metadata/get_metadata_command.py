from dao.metadata_dao import image_metadata_dao
from commands.base_command import BaseCommand

class GetMetadataCommand(BaseCommand):

    def __init__(self, id: str):
        super().__init__()
        self.image_metadata_dao = image_metadata_dao
        self.id = id

    def execute(self):
        self.successful = True

        metadata = image_metadata_dao.get_doc_by_id(self.id)

        return metadata["raw"]

class GetImagesByQRCodes(BaseCommand):

    def __init__(self, qrcodes: list):
        super(GetImagesByQRCodes, self).__init__()
        self.qrcodes = qrcodes
        self.image_metadata_dao = image_metadata_dao

    def execute(self):
        try:
            images_id = []
            for qrcode in self.qrcodes:
                qr_code = qrcode.get("qr_code")
                metadatas = self.image_metadata_dao.get_image_by_qrcode(qr_code)
                qrcode["image_ids"] = []
                if len(metadatas) > 0 :
                    for metadata in metadatas:
                        qrcode["image_ids"].append(metadata.get("_id"))
            self.successful = True
            return self.qrcodes
        except Exception as e:
            self.successful = False
            self.messages.append(str(e))
            return