from commands.challenges.add_new_challenge_command import AddNewChallengeCommand
from commands.challenges.get_all_challenges_command import GetAllChallengesCommand
from tests.test_base import TestBase


class TestChallanges(TestBase):
    def test_add_challenge1(self):
        add_new_challenge_command = AddNewChallengeCommand()

        add_new_challenge_command.input = {
            "name": "Test Case 1 for Challange",
            "status": "RUNNING",
            "description": "Test Case 1 Descsription",
            "rules": "Test Case 1 Rule",
        }

        add_new_challenge_command.execute()
        self.assertTrue(add_new_challenge_command.successful)

    def test_get_challenge2(self):
        add_new_challenge_command = AddNewChallengeCommand()

        add_new_challenge_command.input = {
            "name": "Test Case 2 for Challange",
            "status": "RUNNING",
            "description": "Test Case 2 Descsription",
            "rules": "Test Case 2 Rule",
        }

        add_new_challenge_command.execute()
        self.assertTrue(add_new_challenge_command.successful)

        get_all_challenges_command = GetAllChallengesCommand()
        get_all_challenges_command.execute()
        self.assertTrue(get_all_challenges_command.successful)
