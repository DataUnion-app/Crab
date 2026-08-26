from commands.base_command import BaseCommand
from dao.metadata_dao import image_metadata_dao


class GetTagsByImageStatusCommand(BaseCommand):
    def __init__(self):
        super(GetTagsByImageStatusCommand, self).__init__()
        self.image_metadata_dao = image_metadata_dao

    def execute(self):
        self.successful = True
        status = self.input["status"]

        result = self.image_metadata_dao.get_tags_by_image_status(status)
        return result
