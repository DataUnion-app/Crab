from models.metadata.annotations.base_annotation import BaseAnnotation

from models.metadata.annotations.annotation_type import AnnotationType


class GeoTagging(BaseAnnotation):
    def __init__(self, image_id: str, latitude: float, longitude: float):
        super().__init__()
        self._latitude = latitude
        self._longitude = longitude
        self.image_id = image_id
        self.annotation_type = AnnotationType.GeoLocation

    def get_data(self):
        return {
                   "coordinates": {
                       "latitude": self._latitude,
                       "longitude": self._longitude
                   }
               } | self.get_base_data()

    def get_data_for_db(self):
        return {
            "created_time": self._created_time,
            "coordinates": {
                "latitude": self._latitude,
                "longitude": self._longitude
            },
            "type": self.annotation_type,
            "id": self.annotation_id
        }

    def validate_fields(self):
        return True
