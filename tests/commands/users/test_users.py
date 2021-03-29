from tests.test_base import TestBase
from commands.users.add_user_command import AddUserCommand
from commands.users.get_user_count_command import GetUserCountCommand
from eth_account import Account


class TestUser(TestBase):

    def test_user_command1(self):
        account1 = Account.create()
        add_user = AddUserCommand()
        add_user.input = {
            'public_address': account1.address
        }
        add_user.execute()

        user_count = GetUserCountCommand()
        result = user_count.execute()
        self.assertTrue(True, user_count.successful)
        self.assertEqual({'count': 1}, result)
