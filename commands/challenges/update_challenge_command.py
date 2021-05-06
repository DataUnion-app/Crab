from dao.challenges_dao import challenges_dao
from commands.base_command import BaseCommand
from config import config

class GetAllChallengesCommand(BaseCommand):
     def __init__(self):
        super().__init__()

    def execute(self):

        return True