import datetime
from helpers.load_dummy_data import DummyDataLoader
from tests.test_base import TestBase
from commands.stats.user_stats_command import UserStatsCommand
from tests.dummy_data_helper import DummyDataHelper


class TestMyTagStatsByTimeCommand(TestBase):
    def test_my_tag_stats_1(self):
        loader = DummyDataLoader()
        image_ids = loader.load_random_data2(3, 1, 10, 10)
        address = self.acct.address
        if len(self.default_accounts) > 0:
            address = self.default_accounts[0].address

        DummyDataHelper.mark_images_as_verified(
            address,
            image_ids[:4],
            ["test1"],
            ["t2", "t2_2"],
            ["sample description1", "s2", "s3"],
            ["sample description2"],
        )

        my_tag_stats_command = UserStatsCommand("image")
        my_tag_stats_command.input = {
            "public_address": address,
            'start_date': datetime.datetime.today().strftime('%d-%m-%Y'),
            'end_date': datetime.datetime.today().strftime('%d-%m-%Y')
        }
        result = my_tag_stats_command.execute()
        self.assertTrue(my_tag_stats_command.successful)
        self.assertEqual(1, len(result['verifications']))
