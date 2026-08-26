from models.metadata.annotations.annotation_type import AnnotationType
from models.metadata.annotations.base_annotation import BaseAnnotation


class TagAnnotation(BaseAnnotation):

    def __init__(self, public_address: str, image_id: str, tags: [str]):
        super().__init__()
        self.tags = tags
        self.image_id = image_id
        self.public_address = public_address
        self.annotation_type = AnnotationType.TextTag
        self.validate_fields()

    def get_data(self):
        return {
            "created_time": self._created_time,
            "type": self.annotation_type,
            "public_address": self.public_address,
            "tags": self.tags,
            "updated_time": self.updated_time,
            "id": self.annotation_id
        }

    def get_data_for_db(self):
        return {
            "created_time": self._created_time,
            "type": self.annotation_type,
            "public_address": self.public_address,
            "tags": self.tags,
            "updated_time": self.updated_time,
            "id": self.annotation_id
        }

    def validate_fields(self):
        pass
