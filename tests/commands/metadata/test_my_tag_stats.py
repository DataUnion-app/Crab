from helpers.load_dummy_data import DummyDataLoader
from tests.test_base import TestBase
from commands.metadata.my_tag_stats_command import MyTagStatsCommand
from tests.metadata_helper import MetadataHelper


class TestMyTagStatsCommand(TestBase):

    def test_my_tag_stats_1(self):
        loader = DummyDataLoader()
        image_ids = loader.load_random_data2(6, 1, 1000, 1000)

        my_tag_stats_command = MyTagStatsCommand()
        my_tag_stats_command.input = {
            'public_address': self.acct.address
        }

        MetadataHelper.mark_images_as_verified(self.acct.address, image_ids[:4], ['test1'], ['test2'],
                                               ['sample description1'],
                                               ['sample description2'])

        result = my_tag_stats_command.execute()
        self.assertTrue(my_tag_stats_command.successful)
        self.assertEqual(4, len(result))
