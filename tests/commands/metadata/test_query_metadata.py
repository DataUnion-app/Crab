from commands.metadata.query_metadata_command import QueryMetadataCommand
from helpers.load_dummy_data import DummyDataLoader
from models.ImageStatus import ImageStatus
from tests.test_base import TestBase


class TestQueryMetadataCommand(TestBase):

    def test_query_metadata_1(self):
        dummy_data_loader = DummyDataLoader()
        dummy_data_loader.load_random_data2(10, 4, 10, 10)

        query_metadata_command = QueryMetadataCommand()
        query_metadata_command.input = {
            'status': ImageStatus.AVAILABLE_FOR_TAGGING.name,
            'public_address': '',
            'page': 1,
            'fields': ["image_id"]
        }

        result = query_metadata_command.execute()

        self.assertTrue(query_metadata_command.successful)
        self.assertIsNotNone(result)
        self.assertEqual(10, len(result.get('result')))
