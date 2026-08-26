from typing import List

from models.metadata.annotations.annotation_type import AnnotationType
from models.metadata.annotations.base_annotation import BaseAnnotation


class TrueTag(BaseAnnotation):
    def __init__(
            self,
            public_address: str,
            image_id: str,
            tags: List[str]
    ):
        super().__init__()
        self.annotation_type = AnnotationType.TrueTag
        self.public_address = public_address
        self.image_id = image_id
        self.tags = tags

    def get_data_for_db(self):
        return {
                   "tags": self.tags
               } | self.get_base_data()

    def validate_fields(self):
        pass

    def get_data(self):
        return {
                   "tags": self.tags
               } | self.get_base_data()

