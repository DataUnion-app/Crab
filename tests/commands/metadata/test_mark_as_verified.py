from commands.metadata.add_new_metadata_command import AddNewMetadataCommand
from commands.metadata.verify_image_command import VerifyImageCommand
from models.ImageStatus import ImageStatus
from helpers.load_dummy_data import DummyDataLoader
from eth_account import Account

from tests.test_base import TestBase


class TestMarkAsVerified(TestBase):

    def test_query_metadata_1(self):
        verify_image_command = VerifyImageCommand()
        loader = DummyDataLoader()
        image_ids = loader.load_random_data2(2, 1, 100, 100)

        acct = Account.create()

        verify_image_command.input = {
            'public_address': acct.address,
            'data': image_ids
        }

        verify_image_command.execute()
        self.assertFalse(verify_image_command.successful)

    def test_query_metadata_2(self):
        loader = DummyDataLoader()
        image_ids = loader.load_random_data2(1, 1, 100, 100)

        acct1 = Account.create()
        add_new_metadata_command1 = AddNewMetadataCommand()
        add_new_metadata_command1.input = {
            'public_address': acct1.address,
            'tags': ["abc", "tag2"],
            'photo_id': image_ids[0]
        }
        add_new_metadata_command1.execute()

        acct2 = Account.create()
        add_new_metadata_command2 = AddNewMetadataCommand()
        add_new_metadata_command2.input = {
            'public_address': acct2.address,
            'tags': ["abc", "tag2"],
            'photo_id': image_ids[0]
        }
        add_new_metadata_command2.execute()

        for i in range(10):
            TestMarkAsVerified.mark_as_verified(image_ids, ['abc'], ['123'], [], [])

        status = self.image_metadata_dao.get_doc_by_id(image_ids[0])['status']
        self.assertEqual(ImageStatus.VERIFIED.name, status)

    def test_query_metadata_3(self):
        loader = DummyDataLoader()
        image_ids = loader.load_random_data2(1, 1, 100, 100)

        TestMarkAsVerified.mark_as_verified(image_ids, ['abc'], ['123'], ['test desc'], ['test desc'])

        document = self.image_metadata_dao.get_doc_by_id(image_ids[0])
        status = document['status']
        self.assertEqual(ImageStatus.VERIFIABLE.name, status)

    @staticmethod
    def mark_as_verified(image_ids, tag_up_votes: list[str], tag_down_votes: list[str], desc_up_votes: list[str],
                         desc_down_votes: list[str]):
        acct = Account.create()
        verify_image_command = VerifyImageCommand()
        data = [{'image_id': image_id, 'tags': {'up_votes': tag_up_votes, 'down_votes': tag_down_votes},
                 'descriptions': {'up_votes': desc_up_votes, 'down_votes': desc_down_votes}} for image_id in
                image_ids]
        verify_image_command.input = {
            'public_address': acct.address,
            'data': data
        }

        verify_image_command.execute()
