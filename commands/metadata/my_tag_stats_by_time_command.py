from commands.base_command import BaseCommand
from dao.image_metadata_dao import image_metadata_dao


class MyTagStatsByTimeCommand(BaseCommand):

    def __init__(self):
        super().__init__()
        self.imageMetadataDao = image_metadata_dao

    def execute(self):
        if self.validate_input() is False:
            self.successful = False
            return

        user_tags = self.imageMetadataDao.my_tags(self.input['public_address'])
        result = []

        for row in user_tags:
            data = {'time': row['time'], 'tags_up_votes': len(row['tags_up_votes']),
                    'tags_down_votes': len(row['tags_down_votes']),
                    'descriptions_up_votes': len(row['descriptions_up_votes']),
                    'descriptions_down_votes': len(row['descriptions_down_votes'])}
            result.append(data)
            self.successful = True
        return result

    def validate_input(self):
        if self.input is None:
            self.messages.append("Empty input")
            return False

        if self.input.get('public_address') is None:
            self.messages.append("Missing public_address")
            return False

        if self.input.get('start_time') is None:
            self.messages.append("Missing start_date")
            return False

        if self.input.get('end_time') is None:
            self.messages.append("Missing end_time")
            return False

        return True
