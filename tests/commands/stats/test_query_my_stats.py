from commands.stats.user_stats_command import UserStatsCommand
from models.ImageStatus import ImageStatus
from helpers.load_dummy_data import DummyDataLoader
from helpers.login import Login
from eth_account import Account
import datetime
from tests.test_base import TestBase


class TestMyStatsCommand(TestBase):
    def test_query_my_stats_1(self):
        acct = Account.create()
        login = Login()
        token = login.register_and_login(acct.address, acct.user_id)

        dummy_data_loader = DummyDataLoader()
        image_ids = dummy_data_loader.load_random_data3(acct, token, 2, 10, 10)

        query_my_stats_command = UserStatsCommand("image")
        query_my_stats_command.input = {
            "status": ImageStatus.VERIFIABLE.name,
            "public_address": acct.address,
            'start_date': datetime.datetime.today().strftime('%d-%m-%Y'),
            'end_date': datetime.datetime.today().strftime('%d-%m-%Y')
        }

        result = query_my_stats_command.execute()
        self.assertIsNotNone(result)
        self.assertEqual(1, len(result["uploads"]))
        self.assertEqual(2, result["uploads"][0]['value'])
