from abc import ABC, abstractmethod
from models.metadata.annotations.annotation_type import AnnotationType
from datetime import datetime
from utils.get_random_string import get_random_string


class BaseAnnotation(ABC):
    def __init__(self):
        self._public_address: str = ""
        self._image_id: str = ""
        self._annotation_type = None
        self._created_time = datetime.timestamp(datetime.utcnow())
        self._updated_time = datetime.timestamp(datetime.utcnow())
        self._annotation_id = "annotation:" + get_random_string(15)

    @property
    def public_address(self) -> str:
        return self._public_address

    @public_address.setter
    def public_address(self, value: str):
        self._public_address = value

    @property
    def image_id(self) -> str:
        return self._image_id

    @image_id.setter
    def image_id(self, value: str):
        self._image_id = value

    @property
    def annotation_type(self) -> AnnotationType:
        return self._annotation_type

    @annotation_type.setter
    def annotation_type(self, value: AnnotationType):
        self._annotation_type = value

    @abstractmethod
    def get_data(self):
        pass

    @abstractmethod
    def get_data_for_db(self):
        pass

    def get_base_data(self) -> dict:
        return {
            "public_address": self._public_address,
            "created_time": self._created_time,
            "image_id": self._image_id,
            "updated_time": self._updated_time,
            "type": self.annotation_type,
            "id": self.annotation_id
        }

    @abstractmethod
    def validate_fields(self):
        pass

    @property
    def updated_time(self) -> str:
        return self._updated_time

    @updated_time.setter
    def updated_time(self, value: str):
        self._updated_time = value

    @property
    def created_time(self) -> str:
        return self.created_time

    @updated_time.setter
    def created_time(self, value: str):
        self.created_time = value

    @property
    def annotation_id(self) -> str:
        return self._annotation_id

    @annotation_id.setter
    def annotation_id(self, value: str):
        self._annotation_id = value


class InvalidInputFieldException(Exception):
    pass
