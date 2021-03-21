from commands.metadata.add_new_metadata_command import AddNewMetadataCommand
from helpers.load_dummy_data import DummyDataLoader
from eth_account import Account
from tests.test_base import TestBase
from models.ImageStatus import ImageStatus


class TestMarkAsVerified(TestBase):

    def test_add_metadata_1(self):
        add_new_metadata_command = AddNewMetadataCommand()
        loader = DummyDataLoader()
        image_ids = loader.load_random_data2(1, 1, 100, 100)

        acct = Account.create()

        add_new_metadata_command.input = {
            'public_address': acct.address,
            'tags': ["abc", "tag2"],
            'photo_id': image_ids[0]
        }

        add_new_metadata_command.execute()
        self.assertTrue(add_new_metadata_command.successful)
        self.assertTrue(ImageStatus.AVAILABLE_FOR_TAGGING.name, self.image_metadata_dao.get_doc_by_id(image_ids[0]))

        acct2 = Account.create()
        add_new_metadata_command2 = AddNewMetadataCommand()

        add_new_metadata_command2.input = {
            'public_address': acct2.address,
            'tags': ["abc", "tag2"],
            'photo_id': image_ids[0]
        }

        add_new_metadata_command2.execute()
        self.assertTrue(add_new_metadata_command2.successful)
        updated_status = self.image_metadata_dao.get_doc_by_id(image_ids[0])['status']
        self.assertEqual(ImageStatus.VERIFIABLE.name, updated_status)
