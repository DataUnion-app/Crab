from models.metadata.annotations.annotation_type import AnnotationType
from models.metadata.annotations.base_annotation import BaseAnnotation, InvalidInputFieldException


class AnnotationPeaqDid(BaseAnnotation):

    def __init__(self, entity_id: str, public_address: str, data: dict):
        super().__init__()
        self.entity_id = entity_id
        self.public_address = public_address
        self.data = data
        self.id = ""
        self.annotation_type = AnnotationType.peaq_did
        self.validate_fields()

    def get_data(self):
        self.get_data_for_db()

    def get_data_for_db(self):
        return {
            "entity_id": self.entity_id,
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
