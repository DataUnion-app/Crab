from models.metadata.annotations.annotation_type import AnnotationType
from models.metadata.annotations.base_annotation import BaseAnnotation


class CvatImageIdAnnotation(BaseAnnotation):

    def __init__(self, public_address: str, image_id: str, cvat_image_id: str):
        super().__init__()
        self.public_address = public_address
        self.image_id = image_id
        self.annotation_type = AnnotationType.cvat_id
        self.cvat_image_id = cvat_image_id

    def get_data(self):
        return self.get_data_for_db()

    def get_data_for_db(self):
        return {
            "created_time": self._created_time,
            "type": self.annotation_type,
            "public_address": self.public_address,
            "cvat_image_id": self.cvat_image_id,
            "id": self.annotation_id
        }

    def validate_fields(self):
        pass
