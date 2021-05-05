import unicodedata

from dao.image_metadata_dao import image_metadata_dao
from commands.base_command import BaseCommand
from dao.static_data_dao import WordTypes, static_data_dao


class VerifyImageCommand(BaseCommand):
    MAX_DESCRIPTION_LENGTH = 2000
    MAX_TAG_LENGTH = 200

    def __init__(self):
        super().__init__()
        self.image_metadata_dao = image_metadata_dao
        self.staticdata_dao = static_data_dao

    def execute(self):

        if not self.validate_input():
            self.successful = False
            self.messages.append('Invalid input.')
            return

        self.clean_input()

        if self.has_banned_words():
            self.messages.append("Tags contains banned word(s)")
            self.successful = False
            return

        if not self.has_valid_tag_length():
            self.successful = False
            return

        results = self.image_metadata_dao.mark_as_verified(self.input['data'], self.input['public_address'])

        for result in results:
            if result['success']:
                self.image_metadata_dao.move_to_verified_if_possible(result['image_id'])

        if all(result['success'] is True for result in results):
            self.successful = True
        else:
            self.messages.append('Some or all images are not in verifiable state')
            self.successful = False

    def validate_input(self):
        if not self.input:
            self.messages.append("Empty input body.")
            return False

        if not isinstance(self.input['data'], list):
            self.messages.append('"data" is not a list.')
            return False

        for index, row in enumerate(self.input['data']):
            if not isinstance(row, dict):
                self.messages.append('row in data not an object.')
                return False
            if not row.get('image_id'):
                self.messages.append('missing "image_id" in data.')
                return False
            if not row.get('tags'):
                self.messages.append('missing "tags" in data.')
                return False
            if not isinstance(row['tags'].get('up_votes'), list):
                self.messages.append('"tags.up_votes" is not a list.')
                return False
            if not isinstance(row['tags'].get('down_votes'), list):
                self.messages.append('"tags.down_votes" is not a list.')
                return False
            if not row.get('descriptions'):
                self.input['data'][index]['descriptions'] = {
                    'up_votes': [],
                    'down_votes': []
                }
            if not isinstance(row['descriptions'].get('up_votes'), list):
                self.messages.append('"descriptions.up_votes" is not a list.')
                return False
            if not isinstance(row['descriptions'].get('down_votes'), list):
                self.messages.append('"descriptions.down_votes" is not a list.')
                return False
        return True

    def clean_input(self):
        for index, row in enumerate(self.input['data']):
            self.input['data'][index]["tags"]['up_votes'] = list(map(str.strip, row["tags"]['up_votes']))
            self.input['data'][index]["tags"]['down_votes'] = list(map(str.strip, row["tags"]['down_votes']))
            self.input['data'][index]["descriptions"]['up_votes'] = list(
                map(VerifyImageCommand.remove_control_characters, row["descriptions"]['up_votes']))
            self.input['data'][index]["descriptions"]['down_votes'] = list(
                map(str.strip, row["descriptions"]['down_votes']))

    @staticmethod
    def remove_control_characters(tag):
        return "".join(ch for ch in tag if unicodedata.category(ch)[0] != "C")

    def has_banned_words(self):
        banned_words = self.staticdata_dao.get_words_by_type(WordTypes.BANNED_WORDS.name)
        for index, row in enumerate(self.input['data']):
            tags_lower_case = []
            tags_lower_case = tags_lower_case + list(map(lambda x: x.lower(), row['tags']['up_votes']))
            tags_lower_case = tags_lower_case + list(map(lambda x: x.lower(), row['tags']['down_votes']))
            tags_lower_case = tags_lower_case + list(map(lambda x: x.lower(), row['descriptions']['up_votes']))
            tags_lower_case = tags_lower_case + list(map(lambda x: x.lower(), row['descriptions']['down_votes']))
            banned_words_in_input = list(set(tags_lower_case) & set(banned_words))
            if len(banned_words_in_input) > 0:
                return True
        return False

    def has_valid_tag_length(self):
        for index, row in enumerate(self.input['data']):
            tags = row['tags']['up_votes'] + row['tags']['down_votes']
            all_tags_in_limit = all(
                [len(tag) <= VerifyImageCommand.MAX_TAG_LENGTH for tag in tags])

            if not all_tags_in_limit:
                self.messages.append(
                    "Length of tag(s) exceeds limit of [{0}] characters.".format(VerifyImageCommand.MAX_TAG_LENGTH))
                return False

            descriptions = row['descriptions']['up_votes'] + row['descriptions']['down_votes']
            all_descriptions_in_limit = all(
                [len(description) <= VerifyImageCommand.MAX_DESCRIPTION_LENGTH for description in descriptions])

            if not all_descriptions_in_limit:
                self.messages.append(
                    "Length of description(s) exceeds limit of [{0}] characters.".format(
                        VerifyImageCommand.MAX_DESCRIPTION_LENGTH))
                return False

        return True

    @property
    def is_valid(self):
        pass
