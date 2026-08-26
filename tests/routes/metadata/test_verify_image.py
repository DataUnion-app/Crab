from helpers.load_dummy_data import DummyDataLoader
from tests.test_base import TestBase
from tests.dummy_data_helper import DummyDataHelper
import requests
import json


class TestVerifyImage(TestBase):
    def test_verify_image1(self):
        dummy_data_loader = DummyDataLoader()
        image_id = dummy_data_loader.load_random_data2(1, 1, 50, 50)[0]

        for i in range(2):
            DummyDataHelper.add_metadata(image_id, ["abc", "123"])

        token = self.get_token()
        api_url = self.url + "/api/v1/verify-image"
        headers = {"Authorization": "Bearer {0}".format(token)}
        payload = json.dumps(
            {
                "data": [
                    {
                        "image_id": image_id,
                        "tags": {"up_votes": ["abc"], "down_votes": ["123"]},
                    }
                ]
            }
        )
        response = requests.request("POST", api_url, headers=headers, data=payload)

        self.assertEqual(200, response.status_code)
