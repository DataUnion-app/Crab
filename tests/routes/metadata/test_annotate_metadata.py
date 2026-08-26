import os

from eth_account import Account

from helpers.load_dummy_data import DummyDataLoader
from models.bounty import BountyType
from tests.dummy_data_helper import DummyDataHelper
from tests.test_base import TestBase
import requests
import json


class TestMetadataAnnotate(TestBase):
    def test_metadata_annotate(self):
        dummy_data_loader = DummyDataLoader()
        image_id = dummy_data_loader.load_random_data2(1, 1, 50, 50)[0]

        api_url = self.url + "/api/v1/metadata/annotation"

        payload = {
            "image_id": image_id,
            "annotations": [
                {"type": "box", "tag": "abc", "x": 1.022, "y": 1.36, "width": 21.15, "height": 30.5}
            ],
        }
        headers = {"Authorization": "Bearer {0}".format(self.get_token())}

        response = requests.request(
            "POST",
            api_url,
            headers=headers,
            data=json.dumps(payload),
        )

        self.assertEqual(200, response.status_code)

    def test_metadata_annotate2(self):
        dummy_data_loader = DummyDataLoader()
        image_id = dummy_data_loader.load_random_data2(1, 1, 50, 50)[0]

        api_url = self.url + "/api/v1/metadata/annotation"

        payload = {
            "image_id": image_id,
            "annotations": [
                {"type": "anonymization", "gender": "Male", "skin_color": "Brown", "age": 21}
            ],
        }
        headers = {"Authorization": "Bearer {0}".format(self.get_token())}

        response = requests.request(
            "POST",
            api_url,
            headers=headers,
            data=json.dumps(payload),
        )

        self.assertEqual(200, response.status_code)

    def test_metadata_annotate_pixel(self):
        dummy_data_loader = DummyDataLoader()
        image_id = dummy_data_loader.load_random_images(1, 1, 50, 50)[0]

        api_url = self.url + "/api/v1/metadata/annotation"

        payload = {
            "image_id": image_id,
            "annotations": [
                {"type": "dots", "tag": "random-tag", "dots": [{"x": 1, "y": 1, "height": 1, "width": 1}]}
            ],
        }
        headers = {"Authorization": "Bearer {0}".format(self.get_token())}

        response = requests.request(
            "POST",
            api_url,
            headers=headers,
            data=json.dumps(payload),
        )

        self.assertEqual(200, response.status_code)

    def test_annotate_with_mission_id_1(self):
        account = self.default_accounts[0]
        token = self.get_token_for_account(account)
        sample_image = os.path.join(self.dummy_data_path, 'sample.png')

        dummy_data_loader = DummyDataLoader()
        image_id = dummy_data_loader.upload_image(sample_image, 'sample.png', token)

        assert image_id is not None
        bounty_id = DummyDataHelper.create_dummy_bounty(public_address=Account.create().address,
                                                        bounty_type=BountyType.IMAGE_ANNOTATE,
                                                        number_of_annotations=1000)['id']

        api_url = f"{self.url}/api/v1/missions/info?type=annotate&status=ready_to_start&page=1"
        headers = {"Authorization": f"Bearer {token}"}
        response = requests.get(api_url, headers=headers)

        self.assertEqual(200, response.status_code)
        result = json.loads(response.text)

        mission_info = result['missions'][0]

        api_url = self.url + "/api/v1/metadata/annotation"

        payload = {
            "image_id": mission_info["entity_ids"][0],
            "annotations": [{"type": "anonymization", "gender": "Male", "skin_color": "Brown", "age": 21}],
            "mission_id": mission_info["id"]
        }
        headers = {"Authorization": "Bearer {0}".format(token)}

        response = requests.request(
            "POST",
            api_url,
            headers=headers,
            data=json.dumps(payload),
        )
        self.assertEqual(200, response.status_code)
