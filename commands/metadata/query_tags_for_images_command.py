from dao.metadata_dao import image_metadata_dao
from commands.base_command import BaseCommand
from config import config


class QueryTagsForImagesCommand(BaseCommand):
    MAX_NUMBER_OF_IMAGES = 100

    def __init__(self):
        super().__init__()
        self.image_metadata_dao = image_metadata_dao

    def execute(self):

        is_valid = self.validate_input()

        if is_valid is False:
            self.successful = False
            return

        image_ids = self.input["image_ids"]
        result = self.image_metadata_dao.get_tags_by_image_ids(image_ids)

        self.successful = True
        return result

    def validate_input(self):
        if self.input is None:
            self.messages.append("Empty input")
            return False

        if self.input.get("public_address") is None:
            self.messages.append("Missing public_address")
            return False

        elif not isinstance(self.input.get("image_ids"), list):
            self.messages.append(
                "Invalid input body. Expected `image_ids` to be a list"
            )
            return False
        if len(self.input.get("image_ids")) > 10000:
            self.messages.append(
                f"Max images_ids allowed in single query: [{QueryTagsForImagesCommand.MAX_NUMBER_OF_IMAGES}]"
            )
            return False
        return True
