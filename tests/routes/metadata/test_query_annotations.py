import json

import requests
from helpers.load_dummy_data import DummyDataLoader
from tests.test_base import TestBase
from tests.dummy_data_helper import DummyDataHelper


class TestQueryAnnotations(TestBase):

    def test_query_annotations(self):
        d = DummyDataLoader()
        image_id = d.load_random_data2(1, 1, 100, 100)[0]

        DummyDataHelper.add_bounding_box_annotations(self.acct.address, image_id)

        api_url = self.url + "/api/v1/metadata/query"
        headers = {"Authorization": "Bearer {0}".format(self.get_token())}
        response = requests.request(
            "POST", api_url, headers=headers,
            data=json.dumps({'image_ids': [image_id], 'annotations': ['GeoLocation', 'BoundingBox']})
        )
        data = json.loads(response.text)
        self.assertEqual(response.status_code, 200)
