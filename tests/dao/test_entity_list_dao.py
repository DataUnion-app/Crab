from models.entity_list_models import EntityListType
from models.metadata.metadata_models import EntityType
from tests.test_base import TestBase


class TestEntityListDao(TestBase):
    def test_create_entity_list(self):
        public_address = self.default_accounts[0].address
        doc_id = self.entity_list_dao.create_list(public_address, EntityType.image, ["abc", "123"],
                                                  EntityListType.PUBLIC, 'test')
        self.assertIsNotNone(self.entity_list_dao.get_doc_by_id(doc_id))

        self.entity_list_dao.create_list(public_address, EntityType.image, ["abc2", "123"],
                                         EntityListType.PUBLIC, 'test')
        self.entity_list_dao.create_list(public_address, EntityType.image, ["abc2", "123"],
                                         EntityListType.PRIVATE, 'test')

        self.entity_list_dao.create_list(public_address, EntityType.video, ["abc2", "123"],
                                         EntityListType.PUBLIC, 'test')

        docs = self.entity_list_dao.get_all_public_lists(EntityType.image)
        self.assertEqual(2, len(docs))

        image_lists = self.entity_list_dao.get_user_lists(public_address, EntityType.image)
        self.assertEqual(3, len(image_lists))

        video_lists = self.entity_list_dao.get_user_lists(public_address, EntityType.video)
        self.assertEqual(1, len(video_lists))

    def test_delete_entity_list(self):
        public_address = self.default_accounts[0].address
        doc_id = self.entity_list_dao.create_list(public_address, EntityType.image, ["abc", "123"],
                                                  EntityListType.PUBLIC, 'test')

        self.entity_list_dao.create_list(public_address, EntityType.image, ["abc2", "123"],
                                         EntityListType.PUBLIC, 'test')

        docs = self.entity_list_dao.get_all_public_lists(EntityType.image)
        self.assertEqual(2, len(docs))

        self.entity_list_dao.delete_list(doc_id)

        docs = self.entity_list_dao.get_all_public_lists(EntityType.image)
        self.assertEqual(1, len(docs))

    def test_update_entity_list(self):
        public_address = self.default_accounts[0].address
        doc_id = self.entity_list_dao.create_list(public_address, EntityType.image, ["abc", "123"],
                                                  EntityListType.PUBLIC, 'test')

        self.entity_list_dao.update_list(doc_id, ["xyz"], EntityListType.PRIVATE, 'name 1')

        document = self.entity_list_dao.get_user_lists(public_address, EntityType.image, 1)[0]
        self.assertListEqual(["xyz"], document["entity_ids"])
        self.assertEqual(EntityListType.PRIVATE, document["entity_list_type"])
