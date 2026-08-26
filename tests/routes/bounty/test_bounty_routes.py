from datetime import datetime, timedelta
import json
import os
import requests

from models.bounty import BountyType
from tests.dummy_data_helper import DummyDataHelper
from tests.test_base import TestBase


class TestBountyRoutes(TestBase):

    def __init__(self, *args, **kwargs):
        super(TestBountyRoutes, self).__init__(*args, **kwargs)

    def test_create_bounty(self):
        token = self.default_tokens[0]
        headers = {"Authorization": "Bearer {0}".format(token)}
        api_url = self.url + "/api/v1/bounty/create"
        payload = DummyDataHelper.get_dummy_bounty()

        # Make sure it only accepts the company_image and bounty_image with 400x400 dimension size

        image_path = os.path.join(self.dummy_data_path, "sample.png")
        image_path2 = os.path.join(self.dummy_data_path, "sample2.png")
        img1 = open(image_path, "rb")
        img2 = open(image_path2, "rb")

        files = [("company_image", ("company_image.png", img1, "image/png")),
                 ("bounty_image", ("bounty_image.png", img2, "image/png"))]

        response = requests.request("POST", api_url, headers=headers, data=payload, files=files)
        self.assertEqual(400, response.status_code)
        self.assertIn("company image", response.json()['messages'][0])

        img1.close()
        img2.close()

        img1 = open(image_path, "rb")
        img3 = self.generated_image()

        files = [("company_image", ("company_image.png", img1, "image/png")),
                 ("bounty_image", ("bounty_image.jpg", img3, "image/jpg"))]

        response = requests.request("POST", api_url, headers=headers, data=payload, files=files)
        self.assertEqual(400, response.status_code)
        self.assertIn("company image", response.json()['messages'][0])

        img1.close()
        img3.close()

        img3 = self.generated_image()
        img2 = open(image_path2, "rb")

        files = [("company_image", ("company_image.png", img3, "image/png")),
                 ("bounty_image", ("bounty_image.jpg", img2, "image/jpg"))]

        response = requests.request("POST", api_url, headers=headers, data=payload, files=files)
        self.assertEqual(400, response.status_code)
        self.assertIn("bounty image", response.json()['messages'][0])

        img3.close()
        img2.close()

        img3 = self.generated_image()
        img4 = self.generated_image(color=(31, 63, 121))

        files = [("company_image", ("company_image.jpg", img3, "image/jpg")),
                 ("bounty_image", ("bounty_image.jpg", img4, "image/jpg"))]

        response = requests.request("POST", api_url, headers=headers, data=payload, files=files)
        self.assertEqual(200, response.status_code)
        self.assertTrue(response.json()['id'].startswith('bounty:'))

        img3.close()
        img4.close()

        data = response.json()
        url = f"{self.url}/api/v1/bounty/?id={data['id']}"
        response = requests.request("GET", url, headers=headers, data={})
        self.assertEqual(200, response.status_code)

        # Make sure request params are in the right format

        payload['company_name'] = 'temp_company' * 50
        payload['bounty_name'] = 'temp_bounty' * 50

        img3 = self.generated_image()
        img4 = self.generated_image(color=(31, 63, 121))

        files = [("company_image", ("company_image.jpg", img3, "image/jpg")),
                 ("bounty_image", ("bounty_image.jpg", img4, "image/jpg"))]

        response = requests.request("POST", api_url, headers=headers, data=payload, files=files)
        self.assertEqual(400, response.status_code)
        self.assertEqual(2, len(response.json()['messages']))

        img3.close()
        img4.close()

    def test_create_annotation_bounty(self):
        token = self.default_tokens[0]
        headers = {"Authorization": "Bearer {0}".format(token)}
        api_url = self.url + "/api/v1/bounty/create"

        entity_list_id = DummyDataHelper.generate_new_entity_list(self.default_accounts[0].address, 20)

        payload = DummyDataHelper.get_dummy_bounty(bounty_type=BountyType.IMAGE_ANNOTATE,
                                                   entity_list_ids=[entity_list_id], number_of_annotations=100,
                                                   number_of_verifications=0)

        img3 = self.generated_image()
        img4 = self.generated_image(color=(31, 63, 121))

        files = [("company_image", ("company_image.jpg", img3, "image/jpg")),
                 ("bounty_image", ("bounty_image.jpg", img4, "image/jpg"))]

        response = requests.request("POST", api_url, headers=headers, data=payload, files=files)
        self.assertEqual(200, response.status_code)
        self.assertTrue(response.json()['id'].startswith('bounty:'))

        img3.close()
        img4.close()

    def test_get_bounty_list(self):
        DummyDataHelper.create_dummy_bounty(self.default_accounts[0].address, BountyType.IMAGE_UPLOAD, image_uploads=10)

        DummyDataHelper.create_dummy_bounty(self.default_accounts[0].address, BountyType.IMAGE_ANNOTATE,
                                            number_of_annotations=10)
        DummyDataHelper.create_dummy_bounty(self.default_accounts[0].address, BountyType.IMAGE_VERIFY,
                                            number_of_verifications=10)

        token = self.default_tokens[0]
        headers = {"Authorization": "Bearer {0}".format(token)}
        api_url = self.url + "/api/v1/bounty/list"
        response = requests.request("GET", api_url, headers=headers, data={})
        self.assertEqual(200, response.status_code)
        results = json.loads(response.text)
        self.assertEqual(3, len(results))

    def test_get_images_by_bounty(self):
        token = self.default_tokens[0]
        headers = {"Authorization": "Bearer {0}".format(token)}
        bounty_id = DummyDataHelper.create_dummy_bounty(self.default_accounts[0].address, BountyType.IMAGE_UPLOAD,
                                                        image_uploads=10)['id']

        api_url = f"{self.url}/api/v1/bounty/images_ids?bounty_id={bounty_id}"
        response = requests.request("GET", api_url, headers=headers)

        self.assertEqual(200, response.status_code)
        self.assertEqual(0, len(response.json()))

    def test_handle_images_of_bounty(self):
        token = self.default_tokens[0]
        api_url = self.url + "/api/v1/bounty/image_handler"
        headers = {"Authorization": "Bearer {0}".format(token)}
        bounty_id = DummyDataHelper.create_dummy_bounty(self.default_accounts[0].address, BountyType.IMAGE_UPLOAD,
                                                        image_uploads=10)['id']

        payload = {
            "bounty_id": bounty_id,
            "accepted_image_ids": [1, 2],
            "rejected_image_ids": [2, 3, 4],
        }

        response = requests.request("POST", api_url, headers=headers, data=json.dumps(payload))

        self.assertEqual(True, response.ok)
        self.assertGreater(len(response.json()['accepted_image_ids']), 0)
        self.assertGreater(len(response.json()['rejected_image_ids']), 0)
