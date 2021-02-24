from commands.metadata.verify_image_command import VerifyImageCommand
from models.ImageStatus import ImageStatus
import unittest
from helpers.load_dummy_data import DummyDataLoader
from tests.helper import Helper
from eth_account import Account


class TestMarkAsVerified(unittest.TestCase):

    def test_query_metadata_1(self):
        verify_image_command = VerifyImageCommand()
        loader = DummyDataLoader()
        image_ids = loader.load_random_data2(2, 1, 100, 100)

        acct = Account.create()

        verify_image_command.input = {
            'public_address': acct.address,
            'photos': image_ids
        }

        verify_image_command.execute()
        self.assertTrue(verify_image_command.successful)
