from commands.metadata.add_new_metadata_command import AddNewMetadataCommand
from dao.static_data_dao import WordTypes
from helpers.load_dummy_data import DummyDataLoader
from eth_account import Account
from tests.test_base import TestBase
from models.ImageStatus import ImageStatus


class TestMarkAsVerified(TestBase):
    def test_add_metadata1(self):
        loader = DummyDataLoader()
        image_ids = loader.load_random_data2(1, 1, 100, 100)

        acct = Account.create()
        add_new_metadata_command = AddNewMetadataCommand(public_address=acct.address, mission_id=None)

        add_new_metadata_command.input = {
            "public_address": acct.address,
            "tags": ["abc", "tag2"],
            "image_id": image_ids[0],
        }

        add_new_metadata_command.execute()
        self.assertTrue(add_new_metadata_command.successful)
        self.assertTrue(
            ImageStatus.VERIFIABLE.name,
            self.image_metadata_dao.get_doc_by_id(image_ids[0]),
        )

        acct2 = Account.create()
        add_new_metadata_command2 = AddNewMetadataCommand(public_address=acct2.address, mission_id=None)

        add_new_metadata_command2.input = {
            "public_address": acct2.address,
            "tags": ["abc", "tag2"],
            "image_id": image_ids[0],
        }

        add_new_metadata_command2.execute()
        self.assertTrue(add_new_metadata_command2.successful)
        updated_status = self.image_metadata_dao.get_doc_by_id(image_ids[0])["status"]
        self.assertEqual(ImageStatus.VERIFIABLE.name, updated_status)

    def test_add_metadata2(self):
        loader = DummyDataLoader()
        image_ids = loader.load_random_data2(1, 1, 100, 100)
        self.static_data_dao.add_words(["a55"], WordTypes.BANNED_WORDS.name)
        acct = Account.create()
        add_new_metadata_command = AddNewMetadataCommand(public_address=acct.address, mission_id=None)
        add_new_metadata_command.input = {
            "public_address": acct.address,
            "tags": ["a55", "tag2"],
            "image_id": image_ids[0],
        }

        add_new_metadata_command.execute()
        self.assertFalse(add_new_metadata_command.successful)
        self.assertEqual(
            ["Tags contains banned words ['a55']"], add_new_metadata_command.messages
        )

    def test_add_metadata3(self):
        loader = DummyDataLoader()
        image_ids = loader.load_random_data2(1, 1, 100, 100)

        acct = Account.create()

        add_new_metadata_command = AddNewMetadataCommand(public_address=acct.address, mission_id=None)
        add_new_metadata_command.input = {
            "public_address": acct.address,
            "tags": ["1" * 201, "tag2"],
            "image_id": image_ids[0],
        }

        result = add_new_metadata_command.execute()
        self.assertFalse(add_new_metadata_command.successful)
        self.assertEqual({"status": "failed"}, result)

        add_new_metadata_command2 = AddNewMetadataCommand(public_address=acct.address, mission_id=None)
        add_new_metadata_command2.input = {
            "public_address": acct.address,
            "tags": ["1", "tag2"],
            "image_id": image_ids[0],
            "description": "1" * 2001,
        }

        result = add_new_metadata_command2.execute()
        self.assertFalse(add_new_metadata_command2.successful)
        self.assertEqual({"status": "failed"}, result)
