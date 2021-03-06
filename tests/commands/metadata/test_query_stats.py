from commands.metadata.stats_command import StatsCommand
from models.ImageStatus import ImageStatus
from helpers.load_dummy_data import DummyDataLoader
from helpers.login import Login
from eth_account import Account
from datetime import datetime
from tests.test_base import TestBase
import unittest


class TestStatsCommand(unittest.TestCase):

    def test_query_stats_1(self):
        query_stats_command = StatsCommand()
        query_stats_command.input = {

        }

        result = query_stats_command.execute()

        self.assertTrue(query_stats_command.successful)
        self.assertIsNotNone(result)
        self.assertEqual('success', result.get('status'))
