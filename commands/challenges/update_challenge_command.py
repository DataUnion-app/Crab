from dao.challenges_dao import challenges_dao
from commands.base_command import BaseCommand


class UpdateChallengeCommand(BaseCommand):
    def __init__(self):
        super().__init__()
        self.challenges_dao = challenges_dao

    def execute(self):
        if not self.validate_input():
            self.successful = False
            return {"status": "failed"}

        result = self.challenges_dao.update_challenge(
            self.input["challenge_id"],
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

        if not isinstance(self.input.get("challenge_id"), str):
            self.messages.append("Empty challenge_id")
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
