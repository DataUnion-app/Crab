from commands.metadata.query_metadata_command import QueryMetadataCommand
from models.ImageStatus import ImageStatus
import unittest
from tests.test_base import TestBase


class TestQueryMetadataCommand(TestBase):

    def test_query_metadata_1(self):
        query_metadata_command = QueryMetadataCommand()
        query_metadata_command.input = {
            'status': ImageStatus.AVAILABLE_FOR_TAGGING.name,
            'skip_tagged': True,
            'public_address': '',
            'page': 1
        }

        result = query_metadata_command.execute()
        self.assertIsNotNone(result)
