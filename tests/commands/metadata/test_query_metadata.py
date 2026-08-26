from eth_account import Account

from commands.metadata.query_metadata_command import QueryMetadataCommand
from commands.metadata.search_image_by_tags import SearchImagesByTags
from helpers.load_dummy_data import DummyDataLoader
from models.ImageStatus import ImageStatus
from models.metadata.annotations.annotation_type import AnnotationType
from tests.test_base import TestBase
from tests.dummy_data_helper import DummyDataHelper


class TestQueryMetadataCommand(TestBase):
    def test_query_metadata_1(self):
        dummy_data_loader = DummyDataLoader()
        dummy_data_loader.load_random_data2(2, 1, 10, 10)

        query_metadata_command = QueryMetadataCommand(self.acct.address, 1,
                                                      ImageStatus.VERIFIABLE.name, ["image_id"])

        result = query_metadata_command.execute()

        self.assertTrue(query_metadata_command.successful)
        self.assertIsNotNone(result)
        self.assertEqual(2, len(result.get("result")))

    def test_query_metadata_2(self):
        dummy_data_loader = DummyDataLoader()
        image_ids = dummy_data_loader.load_random_data2(2, 1, 10, 10)

        DummyDataHelper.mark_images_as_verified(self.acct.address, image_ids, ["t1"], ["t2"], [], [])

        acct = Account.create()
        DummyDataHelper.add_bounding_box_annotations(acct.address, image_ids[0])
        query_metadata_command = QueryMetadataCommand(acct.address, 1,
                                                      ImageStatus.VERIFIABLE.name, ["image_id"],
                                                      AnnotationType.BoundingBox)

        result = query_metadata_command.execute()
        self.assertTrue(query_metadata_command.successful)
        self.assertIsNotNone(result)
        self.assertEqual(1, len(result.get("result")))

    def test_query_metadata_3(self):
        dummy_data_loader = DummyDataLoader()
        image_ids = dummy_data_loader.load_random_images(2, 1, 10, 10)
        DummyDataHelper.add_metadata(image_ids[0], ["custom-tag"])

        acct = Account.create()
        query_metadata_command = QueryMetadataCommand(acct.address, 1,
                                                      ImageStatus.VERIFIABLE.name, ["image_id"],
                                                      AnnotationType.Anonymization, "image", ["custom-tag"])

        result = query_metadata_command.execute()
        self.assertTrue(query_metadata_command.successful)
        self.assertIsNotNone(result)
        self.assertEqual(1, len(result.get("result")))

    def test_query_metadata_4(self):
        dummy_data_loader = DummyDataLoader()
        acct = Account.create()

        image_ids = dummy_data_loader.load_random_images(4, 1, 10, 10)
        DummyDataHelper.add_metadata(image_ids[0], ["custom-tag"])
        DummyDataHelper.add_metadata(image_ids[1], ["custom-tag"])
        DummyDataHelper.add_metadata(image_ids[3], ["custom-tag2"])

        DummyDataHelper.mark_images_as_verified(acct.address, [image_ids[1]], ["t1"], ["t2"], [], [])
        DummyDataHelper.add_bounding_box_annotations(acct.address, image_ids[0])

        query_metadata_command = QueryMetadataCommand(acct.address, 1,
                                                      ImageStatus.VERIFIABLE.name, [],
                                                      AnnotationType.TextTag, "image", ["custom-tag"])

        result = query_metadata_command.execute()
        self.assertTrue(query_metadata_command.successful)
        self.assertIsNotNone(result)
        self.assertEqual(1, len(result["result"]))

    def test_query_metadata_5(self):
        dummy_data_loader = DummyDataLoader()
        acct = Account.create()

        image_paths = dummy_data_loader.generate_random_images(100, 100, 4)

        DummyDataHelper.add_new_image(acct.address, image_paths[0], "b1")
        DummyDataHelper.add_new_image(acct.address, image_paths[1], "b2")
        DummyDataHelper.add_new_image(acct.address, image_paths[2], "b1")
        DummyDataHelper.add_new_image(acct.address, image_paths[3], "b4")

        public_address = Account.create().address
        query_metadata_command = QueryMetadataCommand(public_address, 1,
                                                      ImageStatus.VERIFIABLE.name, [],
                                                      AnnotationType.TextTag, "image", None, "b1")

        result = query_metadata_command.execute()
        self.assertTrue(query_metadata_command.successful)
        self.assertIsNotNone(result)
        self.assertEqual(2, len(result["result"]))

    def test_search_entities_by_tags(self):
        account = self.default_accounts[0]
        image_id = DummyDataHelper.add_random_image(account.address, None, None)
        DummyDataHelper.add_metadata(image_id, ['house', 'wood', 'small'])
        DummyDataHelper.add_metadata(image_id, ['tree'])
        for i in range(11):
            image_id = DummyDataHelper.add_random_image(account.address, None, None)
            DummyDataHelper.add_metadata(image_id, ['tiny', 'tree'])

        c = SearchImagesByTags(account.address, ['tiny', 'tree'], 2, 10)
        result = c.execute()
        self.assertTrue(c.successful)
        self.assertEqual(1, len(result["result"]))
        self.assertEqual(11, result["total_count"])
