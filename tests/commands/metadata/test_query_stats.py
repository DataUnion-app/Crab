from commands.metadata.stats_command import StatsCommand
from datetime import datetime
import unittest
from helpers.load_dummy_data import DummyDataLoader


class TestStatsCommand(unittest.TestCase):

    def test_query_stats_1(self):
        query_stats_command = StatsCommand()
        query_stats_command.input = {
        }

        result = query_stats_command.execute()

        self.assertFalse(query_stats_command.successful)
        self.assertIsNone(result)

    def test_query_stats_2(self):
        dummy_data_loader = DummyDataLoader()
        dummy_data_loader.load_random_data2(1, 1, 50, 50)
        query_stats_command = StatsCommand()
        query_stats_command.input = {
            'start_time': 1,
            'end_time': datetime.timestamp(datetime.now()),
            'interval': 1
        }

        result = query_stats_command.execute()

        self.assertTrue(query_stats_command.successful)
        self.assertIsNotNone(result)
        self.assertEqual('success', result.get('status'))
