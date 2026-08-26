from commands.base_command import BaseCommand
from dao.taxonomy_dao import taxonomy_dao


class GetTaxnomonyData(BaseCommand):
    def __init__(self):
        super().__init__()

    def execute(self):
        if not self.validate_input():
            self.successful = False
            return

        result = taxonomy_dao.get_verifiable_images(self.input["public_address"])
        self.successful = True
        return result

    def validate_input(self):
        if not self.input:
            self.messages.append("Empty input")
            return False
        if not isinstance(self.input.get("public_address"), str):
            self.messages.append("Empty public_address")
            return False

        return True
