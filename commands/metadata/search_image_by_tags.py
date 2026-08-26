from typing import List

from commands.base_command import BaseCommand
from dao.metadata_dao import image_metadata_dao
from models.metadata.annotations.annotation_type import AnnotationType
from models.metadata.metadata_models import EntityType


class SearchImagesByTags(BaseCommand):
    def __init__(self, public_address: str, tags: List[str], page: int, page_size: int = 100):
        super(SearchImagesByTags, self).__init__(public_address)
        self.metadata_dao = image_metadata_dao
        self.tags = tags
        self.page = page
        self.page_size = page_size

    def execute(self):
        if not self.validate_input():
            self.successful = False
            return
        result = self.metadata_dao.search_entities_by_tags(EntityType.image, AnnotationType.TextTag,
                                                           self.page, ["_id"], "$and",
                                                           self.tags, self.page_size
                                                           )
        self.successful = True

        return result

    def validate_input(self):
        if self.page_size <= 0 or self.page_size > 1000:
            self.messages.append("Invalid page size.")
            return False
        return True
