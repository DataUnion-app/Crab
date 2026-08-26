from commands.base_command import BaseCommand
from dao.metadata_dao import image_metadata_dao
from models.ImageStatus import ImageStatus


class SearchImageByLocation(BaseCommand):
    def __init__(self, latitude: float, longitude: float, range: float):
        super(SearchImageByLocation, self).__init__()
        self.latitude = latitude
        self.longitude = longitude
        self.range = range
        self.image_metadata_dao = image_metadata_dao

    def execute(self):

        if not self.validate_input():
            self.successful = False
            return
        result = self.image_metadata_dao.search_entity_by_location(
            "image", self.longitude, self.latitude, self.range
        )
        self.successful = True
        return result

    def validate_input(self):
        return True
