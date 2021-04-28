from datetime import datetime
from commands.base_command import BaseCommand
from dao.image_metadata_dao import image_metadata_dao


class MyTagStatsCommand(BaseCommand):

    def __init__(self):
        super().__init__()
        self.imageMetadataDao = image_metadata_dao

    def execute(self):
        if self.validate_input() is False:
            self.successful = False
            return

        result = self.imageMetadataDao.my_tags(self.input['public_address'], 0, datetime.timestamp(datetime.now()))
        total_images = len(result)
        total_tag_up_votes = 0
        total_tag_down_votes = 0
        total_description_up_votes = 0
        total_description_down_votes = 0

        for row in result:
            total_tag_up_votes = total_tag_up_votes + len(row['tags_up_votes'])
            total_tag_down_votes = total_tag_down_votes + len(row['tags_down_votes'])
            total_description_up_votes = total_description_up_votes + len(row['descriptions_up_votes'])
            total_description_down_votes = total_description_down_votes + len(row['descriptions_down_votes'])

        self.successful = True
        return {'total_images': total_images, 'total_tag_up_votes': total_tag_up_votes,
                'total_tag_down_votes': total_tag_down_votes,
                'total_description_up_votes': total_description_up_votes,
                'total_description_down_votes': total_description_down_votes}

    def validate_input(self):
        if self.input is None:
            self.messages.append("Empty input")
            return False

        if self.input.get('public_address') is None:
            self.messages.append("Missing public_address")
            return False

        return True
