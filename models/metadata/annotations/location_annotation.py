from models.metadata.annotations.annotation_type import AnnotationType
from models.metadata.annotations.base_annotation import BaseAnnotation


class LocationAnnotation(BaseAnnotation):

    def __init__(self, public_address: str, image_id: str, latitude: str, longitude: str, locality="", city=""):
        super().__init__()
        self.public_address = public_address
        self.image_id = image_id
        self.annotation_type = AnnotationType.Location
        self.latitude = latitude
        self.longitude = longitude
        self.locality = locality
        self.city = city

    def get_data(self):
        return self.get_data_for_db()

    def get_data_for_db(self):
        return {
            "created_time": self._created_time,
            "type": self.annotation_type,
            "public_address": self.public_address,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "id": self.annotation_id,
            "locality": self.locality,
            "city": self.city
        }

    def validate_fields(self):
        pass
