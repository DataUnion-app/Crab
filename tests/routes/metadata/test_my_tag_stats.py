import json

import requests

from tests.test_base import TestBase
from tests.metadata_helper import MetadataHelper
from helpers.load_dummy_data import DummyDataLoader


class TestMetadata(TestBase):

    def __init__(self, *args, **kwargs):
        super(TestMetadata, self).__init__(*args, **kwargs)

    def test_metadata_query_1(self):
        data_loader = DummyDataLoader()
        image_ids = data_loader.load_random_data2(3, 1)

        MetadataHelper.mark_images_as_verified(self.acct.address, image_ids, ['t1'], ['t2'], ['d2'], ['d3'])
        MetadataHelper.mark_images_as_verified(None, image_ids, ['s1'], ['s2'], ['w2'], ['w3'])

        token = self.get_token()
        headers = {'Authorization': 'Bearer {0}'.format(token)}
        api_url = self.url + "/api/v1/my-tag-stats"
        response = requests.request("GET", api_url, headers=headers, data=json.dumps({}))
        self.assertEqual(200, response.status_code)
        data = json.loads(response.text)

        ids = [doc['image_id'] for doc in data['result']]
        self.assertEqual(sorted(image_ids), sorted(ids))
