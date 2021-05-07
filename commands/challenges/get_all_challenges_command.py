from dao.challenges_dao import challenges_dao
from commands.base_command import BaseCommand


class GetAllChallengesCommand(BaseCommand):
    def __init__(self):
        super().__init__()
        self.challenges_dao = challenges_dao

    def execute(self):
        result = challenges_dao.get_all_challenge()
        self.successful = True
        return result
