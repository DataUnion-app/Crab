import unittest
from web3.auto import w3
from eth_account import Account
from eth_account.messages import defunct_hash_message, encode_defunct
from dao.ImageMetadataDao import ImageMetadataDao


class TestUserDao(unittest.TestCase):

    def setUp(self):
        metadata_dao = ImageMetadataDao()
        metadata_dao.set_config("admin", "admin", "127.0.0.1:5984", "metadata")
        metadata_dao.create_db()

    def test_get_by_id(self):
        metadata_dao = ImageMetadataDao()
        metadata_dao.set_config("admin", "admin", "127.0.0.1:5984", "metadata")

        result = metadata_dao.get_doc_by_id("abc")
        self.assertEqual(result, {"error": "not_found", "reason": "missing"})

    def tearDown(self):
        metadata_dao = ImageMetadataDao()
        metadata_dao.set_config("admin", "admin", "127.0.0.1:5984", "users")
        metadata_dao.delete_db()


if __name__ == '__main__':
    unittest.main()
