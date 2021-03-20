import unittest
from dao.image_metadata_dao import ImageMetadataDao


class TestUserDao(unittest.TestCase):

    def test_get_by_id(self):
        metadata_dao = ImageMetadataDao()
        metadata_dao.set_config("admin", "admin", "127.0.0.1:5984", "metadata")

        result = metadata_dao.get_doc_by_id("abc")
        self.assertEqual(result, {"error": "not_found", "reason": "missing"})


if __name__ == '__main__':
    unittest.main()
