from datetime import datetime
from helpers.load_dummy_data import DummyDataLoader
from tests.test_base import TestBase
from commands.stasts.my_tag_stats_by_time_command import MyTagStatsByTimeCommand
from tests.metadata_helper import MetadataHelper


class TestMyTagStatsByTimeCommand(TestBase):

    def test_my_tag_stats_1(self):
        loader = DummyDataLoader()
        image_ids = loader.load_random_data2(3, 1, 5, 5)
        address = self.acct.address
        if len(self.default_accounts) > 0:
            address = self.default_accounts[0].address

        MetadataHelper.mark_images_as_verified(address, image_ids[:4], ['test1'], ['t2', 't2_2'],
                                               ['sample description1', 's2', 's3'],
                                               ['sample description2'])

        my_tag_stats_command = MyTagStatsByTimeCommand()
        my_tag_stats_command.input = {
            'public_address': address,
            'start_time': 0,
            'end_time': datetime.timestamp(datetime.now()),
            'interval': 24
        }
        result = my_tag_stats_command.execute()
        self.assertTrue(my_tag_stats_command.successful)
        self.assertEqual(1, len(result))
