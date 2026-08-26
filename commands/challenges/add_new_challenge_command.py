from dao.challenges_dao import challenges_dao
from commands.base_command import BaseCommand
from config import config


class AddNewChallengeCommand(BaseCommand):
    MAX_DESCRIPTION_LENGTH = 2000

    def __init__(self):
        super().__init__()
        self.challenges_dao = challenges_dao

    def execute(self):
        if not self.validate_input():
            self.successful = False
            return {"status": "failed"}

        result = self.challenges_dao.add_new_challenge(
            self.input["name"],
            self.input["status"],
            self.input["description"],
            self.input["rules"],
        )
        if result.get("ok") is True:
            self.successful = True
            return {"status": "success"}

        self.successful = False

        return {"status": "failed"}

    def validate_input(self):
        if not self.input:
            self.messages.append("Empty input")
            return False
        if self.input.get("description") is not None:
            if (
                len(self.input.get("description"))
                > AddNewChallengeCommand.MAX_DESCRIPTION_LENGTH
            ):
                self.messages.append(
                    "Length of description exceeds limit of [{0}] characters.".format(
                        AddNewChallengeCommand.MAX_DESCRIPTION_LENGTH
                    )
                )
                return False
        if not isinstance(self.input.get("name"), str):
            self.messages.append("Empty name")
            return False

        if not isinstance(self.input.get("status"), str):
            self.messages.append("Empty status")
            return False

        if not isinstance(self.input.get("rules"), str):
            self.messages.append("Empty rules")
            return False

        return True
