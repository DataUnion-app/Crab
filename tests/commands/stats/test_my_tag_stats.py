from helpers.load_dummy_data import DummyDataLoader
from tests.test_base import TestBase
from commands.stasts.my_tag_stats_command import MyTagStatsCommand
from tests.metadata_helper import MetadataHelper


class TestMyTagStatsCommand(TestBase):

    def test_my_tag_stats_1(self):
        loader = DummyDataLoader()
        image_ids = loader.load_random_data2(6, 1, 1000, 1000)

        my_tag_stats_command = MyTagStatsCommand()
        my_tag_stats_command.input = {
            'public_address': self.acct.address
        }

        MetadataHelper.mark_images_as_verified(self.acct.address, image_ids[:4], ['test1'], ['t2', 't2_2'],
                                               ['sample description1', 's2', 's3'],
                                               ['sample description2'])

        result = my_tag_stats_command.execute()
        self.assertTrue(my_tag_stats_command.successful)
        self.assertEqual({'total_images': 4, 'total_tag_up_votes': 4,
                          'total_tag_down_votes': 8,
                          'total_description_up_votes': 12,
                          'total_description_down_votes': 4}, result)
