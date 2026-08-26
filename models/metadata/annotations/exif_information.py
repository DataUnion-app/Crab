from models.metadata.annotations.base_annotation import BaseAnnotation

from models.metadata.annotations.annotation_type import AnnotationType


class ExifInformation(BaseAnnotation):
    def __init__(self, image_id: str, data: dict):
        super().__init__()
        self._data = data
        self.image_id = image_id
        self.annotation_type = AnnotationType.ExifInformation

    def get_data(self):
        return {
            "data": self._data,
        } | self.get_base_data()

    def get_data_for_db(self):
        return {
            "created_time": self._created_time,
            "type": self.annotation_type,
            "data": self._data,
        }

    def validate_fields(self):
        return True
