import unittest
from dao.metadata_dao import ImageMetadataDao
from models.metadata.metadata_models import EntityType
from tests.test_base import TestBase


class TestUserDao(TestBase):
    def test_get_by_id(self):
        metadata_dao = ImageMetadataDao()
        metadata_dao.set_config("admin", "admin", "127.0.0.1:5984", "metadata")

        result = metadata_dao.get_doc_by_id("abc")
        self.assertEqual(result, {"error": "not_found", "reason": "missing"})

    def test_get_docs_type(self):
        public_address = self.default_accounts[0].address
        self.image_metadata_dao.add_new_image_entity("123", public_address, "123.png", "123.png", 10, 10, ["general"])
        result = self.image_metadata_dao.get_docs_type(["123"])
        self.assertIsNotNone(result)
        self.assertListEqual([EntityType.image], result)
        

if __name__ == "__main__":
    unittest.main()
