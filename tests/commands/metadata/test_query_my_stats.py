from commands.metadata.my_stats_command import MyStatsCommand
from models.ImageStatus import ImageStatus
import unittest
from helpers.load_dummy_data import DummyDataLoader
from helpers.login import Login
from eth_account import Account
from datetime import datetime
from tests.test_base import TestBase


class TestMyStatsCommand(TestBase):

    def test_query_my_stats_1(self):
        acct = Account.create()
        login = Login()
        token = login.register_and_login(acct.address, acct.key)

        dummy_data_loader = DummyDataLoader()
        image_ids = dummy_data_loader.load_random_data3(acct, token, 2, 2, 2)

        query_my_stats_command = MyStatsCommand()
        query_my_stats_command.input = {
            'status': ImageStatus.AVAILABLE_FOR_TAGGING.name,
            'public_address': acct.address,
            'start_time': 1,
            'end_time': datetime.timestamp(datetime.now())
        }

        result = query_my_stats_command.execute()
        self.assertIsNotNone(result)
        self.assertEqual('success', result.get('status'))

