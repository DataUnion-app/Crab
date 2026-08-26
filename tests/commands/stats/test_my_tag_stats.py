from helpers.load_dummy_data import DummyDataLoader
from tests.test_base import TestBase
from commands.stats.user_stats_command import UserStatsCommand
from tests.dummy_data_helper import DummyDataHelper
import datetime


class TestMyTagStatsCommand(TestBase):
    def test_my_tag_stats_1(self):
        loader = DummyDataLoader()
        image_ids = loader.load_random_data2(6, 1, 10, 10)

        my_tag_stats_command = UserStatsCommand("image")
        date_today = datetime.datetime.today().strftime('%d-%m-%Y')
        my_tag_stats_command.input = {"public_address": self.acct.address,
                                      'start_date': date_today,
                                      'end_date': date_today}

        DummyDataHelper.mark_images_as_verified(
            self.acct.address,
            image_ids[:4],
            ["test1"],
            ["t2", "t2_2"],
            ["sample description1", "s2", "s3"],
            ["sample description2"],
        )

        result = my_tag_stats_command.execute()
        self.assertTrue(my_tag_stats_command.successful)
        self.assertEqual(
            {'pixel_annotations': [],
             'tag_annotations': [],
             'text_annotations': [],
             'uploads': [],
             'verifications': [{'date': date_today, 'value': 28}]},
            result,
        )
