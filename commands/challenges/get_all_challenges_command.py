from dao.challenges_dao import challenges_dao
from commands.base_command import BaseCommand
from config import config

class GetAllChallengesCommand(BaseCommand):
    def __init__(self):
        super().__init__()

    def execute(self):
        if not self.validate_input():
            self.successful = False
            return

        # result = challenges_dao.get_verifiable_images(self.input['public_address'])
        # self.successful = True
        return True