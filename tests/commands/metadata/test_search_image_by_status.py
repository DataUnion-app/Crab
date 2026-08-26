from tests.test_base import TestBase
from helpers.load_dummy_data import DummyDataLoader
from commands.metadata.search_image_by_status import SearchImagesByStatus


class TestSearchImageByStatus(TestBase):
    def test_search_image_by_status1(self):
        DummyDataLoader().load_random_images(1, 1, 100, 100)
        s = SearchImagesByStatus(1, "VERIFIABLE")
        result = s.execute()
        self.assertTrue(s.successful)
        self.assertTrue(len(result['data']), 1)
