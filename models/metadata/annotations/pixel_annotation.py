from models.metadata.annotations.annotation_type import AnnotationType
from models.metadata.annotations.base_annotation import BaseAnnotation


class PixelBox(object):
    def __init__(self, x: int, y: int, height: int, width: int):
        self.x = x
        self.y = y
        self.height = height
        self.width = width

    def as_dict(self):
        return dict({
            'x': self.x,
            'y': self.y,
            'height': self.height,
            'width': self.width,
        })


class PixelAnnotation(BaseAnnotation):

    def __init__(self, public_address: str, image_id: str, tag: str, boxes: list):
        super().__init__()
        self.public_address = public_address
        self.image_id = image_id
        self.annotation_type = AnnotationType.Pixel
        self.boxes = boxes
        self.tag = tag

    def get_data(self):
        return {
                   "boxes": [box.as_dict() for box in self.boxes],
               } | self.get_base_data()

    def get_data_for_db(self):
        return {
            "public_address": self.public_address,
            "created_time": self._created_time,
            "updated_time": self.updated_time,
            "type": self.annotation_type,
            "boxes": [box.as_dict() for box in self.boxes],
            "tag": self.tag,
            "id": self.annotation_id
        }

    def validate_fields(self):
        pass
