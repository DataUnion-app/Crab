from models.metadata.annotations.annotation_type import AnnotationType
from models.metadata.annotations.base_annotation import BaseAnnotation, InvalidInputFieldException


class Anonymization(BaseAnnotation):
    SUPPORTED_GENDERS = ["male", "female", "other"]

    def __init__(self, public_address: str, image_id: str, age: float, gender: str, skin_color: str):
        super().__init__()
        self.age = age
        self.gender = gender.lower()
        self.image_id = image_id
        self.skin_color = skin_color.lower()
        self.public_address = public_address
        self.annotation_type = AnnotationType.Anonymization
        self.validate_fields()

    def get_data(self):
        return self.get_data_for_db()

    def get_data_for_db(self):
        return {
            "age": self.age,
            "gender": self.gender,
            "skin_color": self.skin_color,
            "public_address": self._public_address,
            "created_time": self._created_time,
            "type": self.annotation_type,
            "id": self.annotation_id
        }

    def validate_fields(self):
        if self.age < 0 or self.age > 150:
            raise InvalidInputFieldException(f"Invalid age [{self.age}] in [{self.annotation_type}]")
        if self.gender not in Anonymization.SUPPORTED_GENDERS:
            raise InvalidInputFieldException(f"Unsupported gender [{self.gender}]")
        if len(self.skin_color) > 100:
            raise InvalidInputFieldException(f"skin_color value too large.")
