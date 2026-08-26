from models.metadata.annotations.annotation_type import AnnotationType
from models.metadata.annotations.base_annotation import BaseAnnotation, InvalidInputFieldException
from dao.metadata_dao import image_metadata_dao


class AnnotationDataShareReport(BaseAnnotation):

    def __init__(self, data_share_id: str, public_address: str, data: dict):
        super().__init__()
        self.data_share_id = data_share_id
        self.public_address = public_address
        self.data = data
        self.id = ""
        self.annotation_type = AnnotationType.data_share_report
        self.validate_fields()

    def get_data(self):
        self.get_data_for_db()

    def get_data_for_db(self):
        return {
            "data_share_id": self.data_share_id,
            "public_address": self.public_address,
            "data": self.data,
            "created_time": self._created_time,
            "type": self.annotation_type,
            "id": self.annotation_id
        }

    def validate_fields(self):
        if not self.data:
            raise InvalidInputFieldException(f"Data is empty")
        pass
