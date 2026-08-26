from commands.base_command import BaseCommand
from dao.metadata_dao import image_metadata_dao


class ImageResult(BaseCommand):
    def __init__(self):
        super(ImageResult, self).__init__()
        self.image_metadata_dao = image_metadata_dao

    def execute(self):

        result = self.image_metadata_dao.image_result(
            self.input["image_id"], self.input["option"]
        )
        self.successful = True
        return result

