from models.metadata.annotations.base_annotation import BaseAnnotation
from models.metadata.annotations.annotation_type import AnnotationType


class BoundingBox(BaseAnnotation):

    def __init__(
            self,
            public_address: str,
            image_id: str,
            tag: str,
            x: float,
            y: float,
            height: float,
            width: float,
    ):
        super().__init__()
        self.annotation_type = AnnotationType.BoundingBox
        self.public_address = public_address
        self._x = x
        self._y = y
        self._height = height
        self._width = width
        self.image_id = image_id
        self._tag = tag

    def get_data(self) -> dict:
        return {
                   "x": self._x,
                   "y": self._y,
                   "height": self._height,
                   "width": self._width,
               } | self.get_base_data()

    def get_data_for_db(self) -> dict:
        return {
            "x": self._x,
            "y": self._y,
            "height": self._height,
            "width": self._width,
            "public_address": self.public_address,
            "created_time": self._created_time,
            "type": self.annotation_type,
            "tag": self._tag,
            "id": self.annotation_id
        }

    def validate_fields(self):
        pass
