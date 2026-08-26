from commands.base_command import BaseCommand
from dao.metadata_dao import image_metadata_dao
from models.ImageStatus import ImageStatus


class SearchImagesByStatus(BaseCommand):
    def __init__(self, page: int, status: str):
        super(SearchImagesByStatus, self).__init__()
        self.page = page
        self.status = status
        self.image_metadata_dao = image_metadata_dao

    def execute(self):

        if not self.validate_input():
            self.successful = False
            return
        result = self.image_metadata_dao.search_entity_by_status(
            self.page, "image", self.status
        )
        self.successful = True
        return result

    def validate_input(self):

        if self.page <= 0:
            self.messages.append("'page' is not a valid value.")
            return False

        if self.status not in ImageStatus.__members__:
            self.messages.append("'status' is not a valid value.")
            return False

        return True
