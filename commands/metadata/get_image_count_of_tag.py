from commands.base_command import BaseCommand
from dao.metadata_dao import image_metadata_dao


class GetImageCountByTag(BaseCommand):
    def __init__(self, tag_names: list):
        super(GetImageCountByTag, self).__init__()
        self.tag_names = tag_names
        self.image_metadata_dao = image_metadata_dao

    def execute(self):
        image_counts = self.image_metadata_dao.get_image_counts_for_tags(self.tag_names)

        if not image_counts:
            self.messages.append("Can't find image counts for a given tag in the database")
            self.successful = False
            return

        self.successful = True
        return image_counts
