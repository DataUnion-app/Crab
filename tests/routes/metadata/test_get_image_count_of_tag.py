import os
from eth_account import Account
from helpers.load_dummy_data import DummyDataLoader
from tests.test_base import TestBase
from tests.dummy_data_helper import DummyDataHelper
import requests
import json


class TestGetImageCountOfTag(TestBase):
    def test_get_image_count_of_tag(self):
        token = self.get_token()
        account = self.default_accounts[0]
        headers = {"Authorization": "Bearer {0}".format(token)}

        api_url = self.url + "/api/v1/upload-file"
        payload = {"uploaded_by": account.address}
        with self.generated_image() as img:
            files = [("file", ("sample.png", img, "image/jpg"))]

            response = requests.request(
                "POST", api_url, headers=headers, data=payload, files=files
            )
            data = json.loads(response.text)
            image_id = data["id"]

        api_url = self.url + "/api/v1/annotate"
        data = {"image_id": image_id, "tags": ["t1", "t2"]}
        response = requests.request(
            "POST", api_url, headers=headers, data=json.dumps(data)
        )

        api_url = f"{self.url}/api/v1/metadata/tag-image-count?tag_name=t1&tag_name=t2"
        response = requests.request("GET", api_url, headers=headers)

        self.assertEqual(200, response.status_code)
        self.assertEqual(2, len(response.json()['result']))
