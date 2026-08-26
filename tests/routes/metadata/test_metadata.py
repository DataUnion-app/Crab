import unittest
from eth_account import Account

import json
import os
import shutil
import requests
from eth_account.messages import encode_defunct
from web3.auto import w3

from helpers.change_whitelist_status import update_whitelist
from helpers.load_dummy_data import DummyDataLoader
from models.metadata.metadata_models import Source, Network
from utils.get_project_dir import get_project_root
from models.ImageStatus import ImageStatus
from tests.test_base import TestBase
from models.metadata.annotations.annotation_type import AnnotationType


class TestMetadata(TestBase):
    def __init__(self, *args, **kwargs):
        self.url = "http://localhost:8080"
        self.db_host = "127.0.0.1:5984"
        self.db_user = "admin"
        self.password = "admin"
        self.data_dir = os.path.join(get_project_root(), "data")
        self.dummy_data_path = os.path.join(get_project_root(), "tests", "data")
        super(TestMetadata, self).__init__(*args, **kwargs)

    def test_add_image(self):
        acct = Account.create()

        # This is for non source case
        token = TestMetadata.get_token_for_account(acct)
        headers = {"Authorization": "Bearer {0}".format(token)}

        api_url = self.url + "/api/v1/upload-file"

        payload = {
            "latitude": 123,
            "longitude": 123123,
            "bounty": "general"
        }
        with self.generated_image() as img:
            files = [("file", ("sample.jpg", img, "image/jpg"))]

            response = requests.request(
                "POST", api_url, headers=headers, data=payload, files=files
            )
            self.assertTrue(response.status_code, 200)
            data = json.loads(response.text)
            image_id = data["id"]
            self.assertTrue(image_id is not None)

        # This is for the case that involves source field in the access token
        token = TestMetadata.get_token_for_account(acct, Source.other)
        headers = {"Authorization": "Bearer {0}".format(token)}
        payload = {
            "latitude": 1234,
            "longitude": 1231231,
            "bounty": "general"
        }
        with self.generated_image() as img:
            files = [("file", ("sample5.jpg", img, "image/jpg"))]

            response = requests.request(
                "POST", api_url, headers=headers, data=payload, files=files
            )
            self.assertTrue(response.status_code, 200)
            data = json.loads(response.text)
            image_id = data["id"]
            self.assertTrue(image_id is not None)

        # This is for the case that involves annotations
        payload = {
            "annotations": """[
                {
                    "type": "box",
                    "x": 2.0,
                    "y": 3.4,
                    "width": 5.0,
                    "height": 34,
                    "tag": "abc"
                },{
                    "type": "box",
                    "x": 6.0,
                    "y": 2.4,
                    "width": 6.0,
                    "height": 36,
                    "tag": "abc"
                }, {
                    "type": "dots",
                    "tag": "random-tag",
                    "dots": [{"x": 1, "y": 1, "height": 1, "width": 1}]
                }
            ]""",
            "bounty": "general"
        }
        with self.generated_image() as img:
            files = [("file", ("sample6.png", img, "image/jpg"))]

            response = requests.request(
                "POST", api_url, headers=headers, data=payload, files=files
            )
            self.assertTrue(response.status_code, 200)
            data = json.loads(response.text)
            image_id = data["id"]
            self.assertTrue(image_id is not None)

    def test_upload_video_in_new_way(self):
        acct = Account.create()
        token = TestMetadata.get_token_for_account(acct)
        headers = {"Authorization": "Bearer {0}".format(token)}

        api_url = self.url + "/api/v1/upload-file"
        with self.generated_media() as img:
            files = [("file", ("test-video.mp4", img, "video/mp4"))]

            response = requests.request(
                "POST", api_url, headers=headers, data={}, files=files
            )
            self.assertEqual(response.status_code, 200)
            data = json.loads(response.text)
            video_id = data["id"]
            self.assertTrue(video_id is not None)

    def test_upload_audio(self):
        acct = Account.create()
        token = TestMetadata.get_token_for_account(acct)
        headers = {"Authorization": "Bearer {0}".format(token)}

        api_url = self.url + "/api/v1/upload-file"
        with self.generated_media() as audio:
            files = [("file", ("generated-audio.mp3", audio))]

            response = requests.request(
                "POST", api_url, headers=headers, data={}, files=files
            )
            self.assertEqual(response.status_code, 200)
            data = json.loads(response.text)
            video_id = data["id"]
            self.assertTrue(video_id is not None)

    def test_add_image_twice(self):
        acct = Account.create()
        token = self.get_token_for_account(acct)
        headers = {"Authorization": "Bearer {0}".format(token)}

        api_url = self.url + "/api/v1/upload-file"

        payload = {"uploaded_by": acct.address}
        image_path = os.path.join(self.dummy_data_path, "sample.png")

        with open(image_path, "rb") as img:
            files = [("file", ("sample.png", img, "image/png"))]

            response = requests.request(
                "POST", api_url, headers=headers, data=payload, files=files
            )
            self.assertTrue(response.status_code, 200)
            data = json.loads(response.text)
            image_id = data["id"]
            self.assertTrue(image_id is not None)

        image_path2 = os.path.join(self.dummy_data_path, "sample2.png")
        with open(image_path2, "rb") as img2:
            files2 = [("file", ("sample2.png", img2, "image/png"))]

            response = requests.request(
                "POST", api_url, headers=headers, data=payload, files=files2
            )
            self.assertTrue(response.status_code, 400)
            data = json.loads(response.text)
            self.assertEqual(
                data,
                {
                    "messages": ["The uploaded file already exists in the dataset."],
                    "status": "failed",
                },
            )

    def test_metadata_to_image(self):
        acct = Account.create()
        token = TestMetadata.get_token_for_account(acct)
        headers = {"Authorization": "Bearer {0}".format(token)}

        api_url = self.url + "/api/v1/upload-file"
        payload = {"uploaded_by": acct.address}
        image_path = os.path.join(self.dummy_data_path, "sample.png")

        with open(image_path, "rb") as img:
            files = [("file", ("sample.png", img, "image/png"))]

            response = requests.request(
                "POST", api_url, headers=headers, data=payload, files=files
            )
            self.assertTrue(response.status_code, 200)
            data = json.loads(response.text)
            image_id = data["id"]
            self.assertTrue(image_id is not None)

        api_url = self.url + "/api/v1/annotate"
        data = {
            "image_id": image_id,
            "tags": ["t1  ", "  t2", " t3\t "],
            "description": "test",
        }
        response = requests.request(
            "POST", api_url, headers=headers, data=json.dumps(data)
        )
        self.assertTrue(response.status_code, 200)

        p = self.image_metadata_dao.get_doc_by_id(image_id)
        result = [x for x in p["annotations"] if x['type'] == AnnotationType.TextTag]

        self.assertEqual(1, len(result))
        self.assertEqual(["t1", "t2", "t3"], result[0].get("tags"))
        self.assertEqual(acct.address, result[0].get("public_address"))

        text_annotations = [x for x in p["annotations"] if x['type'] == AnnotationType.TextDescription]
        self.assertEqual(1, len(text_annotations))
        self.assertEqual("test", text_annotations[0]["text"])

        acct2 = Account.create()
        api_url = self.url + "/api/v1/annotate"
        token2 = TestMetadata.get_token_for_account(acct2)
        headers2 = {"Authorization": "Bearer {0}".format(token2)}
        data2 = {"image_id": image_id, "timestamp": "", "tags": ["u1", "u2"]}
        response2 = requests.request(
            "POST", api_url, headers=headers2, data=json.dumps(data2)
        )
        self.assertTrue(response2.status_code, 200)

        annotations = self.image_metadata_dao.get_doc_by_id(image_id)["annotations"]
        result = [x for x in annotations if x['type'] == AnnotationType.TextTag]
        self.assertEqual(2, len(result))
        self.assertEqual(["u1", "u2"], result[1].get("tags"))
        self.assertEqual(acct2.address, result[1].get("public_address"))

    def test_get_all_metadata(self):
        acct = Account.create()
        token = TestMetadata.get_token_for_account(acct)
        headers = {"Authorization": "Bearer {0}".format(token)}

        api_url = self.url + "/api/v1/my-metadata"
        response = requests.request(
            "GET", api_url, headers=headers, data=json.dumps({})
        )
        data = json.loads(response.text)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(data, {"result": [], "page": 1, "page_size": 100})

        api_url = self.url + "/api/v1/my-metadata?page=3"
        response = requests.request(
            "GET", api_url, headers=headers, data=json.dumps({})
        )
        data = json.loads(response.text)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(data, {"result": [], "page": 3, "page_size": 100})

    def test_search_images_by_status(self):
        acct = Account.create()
        token = TestMetadata.get_token_for_account(acct)
        headers = {"Authorization": "Bearer {0}".format(token)}
        api_url = f"{self.url}/api/v1/search-images-by-status"
        body = {
            'page': '1',
            'status': 'VERIFIABLE'
        }

        # Make sure this user can't retrieve images due to invalid
        response = requests.get(api_url, headers=headers, params=body)
        self.assertEqual(response.status_code, 403)

        # Allow the user to retrieve images by status by adding the user address
        # to the whitelist...
        update_whitelist(acct.address)
        response = requests.get(api_url, headers=headers, params=body)
        self.assertEqual(response.status_code, 200)

    def test_get_my_images(self):

        acct = Account.create()
        token = TestMetadata.get_token_for_account(acct)
        headers = {"Authorization": "Bearer {0}".format(token)}

        api_url = self.url + "/api/v1/my-images"
        response = requests.request(
            "GET", api_url, headers=headers, data=json.dumps({})
        )
        data = json.loads(response.text)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(data, {"result": [], "page": 1, "page_size": 100})

        api_url = self.url + "/api/v1/my-images?page=30"
        response = requests.request(
            "GET", api_url, headers=headers, data=json.dumps({})
        )
        data = json.loads(response.text)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(data, {"result": [], "page": 30, "page_size": 100})

    def test_mark_as_reported(self):
        acct = Account.create()
        token = TestMetadata.get_token_for_account(acct)
        headers = {"Authorization": "Bearer {0}".format(token)}
        api_url = self.url + "/api/v1/report-images"
        data = {}
        response = requests.request(
            "POST", api_url, headers=headers, data=json.dumps(data)
        )

        self.assertEqual(400, response.status_code)
        self.assertEqual(
            {
                "messages": ["Invalid input body. Expected 'photos' to be a list."],
                "status": "failed",
            },
            json.loads(response.text),
        )

        acct = Account.create()
        token = TestMetadata.get_token_for_account(acct)
        headers = {"Authorization": "Bearer {0}".format(token)}
        images = self.image_metadata_dao.get_by_status(ImageStatus.VERIFIABLE.name)
        data = {"photos": [{"photo_id": image["_id"]} for image in images["result"]]}
        response = requests.request(
            "POST", api_url, headers=headers, data=json.dumps(data)
        )
        self.assertEqual(200, response.status_code)
        self.assertEqual({"status": "success"}, json.loads(response.text))

    def test_mark_as_reported2(self):

        dummy_data_loader = DummyDataLoader()
        image_id = dummy_data_loader.load_random_data2(1, 1, 500, 500)[0]

        headers = {"Authorization": "Bearer {0}".format(self.get_token())}
        api_url = self.url + "/api/v1/report-images"
        data = {"photos": [{"photo_id": image_id}]}
        response = requests.request(
            "POST", api_url, headers=headers, data=json.dumps(data)
        )

        self.assertEqual(200, response.status_code)
        doc = self.image_metadata_dao.get_doc_by_id(image_id)
        self.assertEqual(ImageStatus.VERIFIABLE.name, doc["status"])

    def test_mark_as_reported3(self):

        dummy_data_loader = DummyDataLoader()
        image_id = dummy_data_loader.load_random_data2(1, 1, 500, 500)[0]

        headers = {"Authorization": "Bearer {0}".format(self.get_token())}
        api_url = self.url + "/api/v1/report-images"
        data = {"photos": [{"photo_id": image_id}]}
        response = requests.request(
            "POST", api_url, headers=headers, data=json.dumps(data)
        )
        self.assertEqual(200, response.status_code)

        acct = Account.create()
        token = TestMetadata.get_token_for_account(acct)

        headers = {"Authorization": f"Bearer {token}"}
        api_url = self.url + "/api/v1/report-images"
        data = {"photos": [{"photo_id": image_id}]}
        response = requests.request(
            "POST", api_url, headers=headers, data=json.dumps(data)
        )
        self.assertEqual(200, response.status_code)

        acct = Account.create()
        token = TestMetadata.get_token_for_account(acct)

        headers = {"Authorization": f"Bearer {token}"}
        api_url = self.url + "/api/v1/report-images"
        data = {"photos": [{"photo_id": image_id}]}
        response = requests.request(
            "POST", api_url, headers=headers, data=json.dumps(data)
        )
        self.assertEqual(200, response.status_code)

        doc = self.image_metadata_dao.get_doc_by_id(image_id)
        self.assertEqual(ImageStatus.REPORTED_AS_INAPPROPRIATE.name, doc["status"])

    def clear_data_directory(self):
        for filename in os.listdir(self.data_dir):
            file_path = os.path.join(self.data_dir, filename)
            if filename == ".gitkeep":
                continue
            try:
                if os.path.isfile(file_path) or os.path.islink(file_path):
                    os.unlink(file_path)
                elif os.path.isdir(file_path):
                    shutil.rmtree(file_path)
            except Exception as e:
                print("Failed to delete %s. Reason: %s" % (file_path, e))

    def test_upload_video(self):
        acct = Account.create()
        token = TestMetadata.get_token_for_account(acct)
        headers = {"Authorization": "Bearer {0}".format(token)}

        api_url = self.url + "/api/v1/videos/upload"
        with self.generated_media() as img:
            files = [("file", ("test-video.mp4", img, "video/mp4"))]

            response = requests.request(
                "POST", api_url, headers=headers, data={}, files=files
            )
            self.assertEqual(response.status_code, 200)
            data = json.loads(response.text)
            video_id = data["id"]
            self.assertTrue(video_id is not None)

            # Uploading the same file again
            # response = requests.request(
            #     "POST", api_url, headers=headers, data=payload, files=files
            # )
            # data = json.loads(response.text)
            # self.assertTrue(response.status_code, 400)
            # self.assertEqual(
            #     data,
            #     {
            #         "messages": ["The uploaded file already exists in the dataset."],
            #         "status": "failed",
            #     },
            # )

    def test_web3_entity(self):
        token = self.default_tokens[0]
        headers = {"Authorization": "Bearer {0}".format(token)}
        api_url = self.url + "/api/v1/metadata/web3-wallet"
        payload = json.dumps({"wallet_address": "", "signature": ""})

        response = requests.request("POST", api_url, headers=headers, data=payload)
        self.assertEqual(400, response.status_code)
        self.assertEqual("Invalid signature", json.loads(response.text)["messages"][0])

        nonce = "1"
        account = Account.create()
        private_key = account.key
        message = encode_defunct(text=nonce)
        signed_message = w3.eth.account.sign_message(message, private_key=private_key)
        signature = signed_message.signature

        # Get nonce
        nonce_api_url = self.url + f"/api/v1/metadata/web3-wallet/nonce?wallet_address={account.address}"
        response = requests.request("GET", nonce_api_url, headers=headers, data={})
        self.assertEqual(200, response.status_code)

        nonce = response.json()["nonce"]
        message = encode_defunct(text=nonce)
        signed_message = w3.eth.account.sign_message(message, private_key=private_key)
        signature = signed_message.signature

        payload = json.dumps({"wallet_address": account.address,
                              "signature": signature.hex(),
                              "network": Network.eth_mainnet})

        response = requests.request("POST", api_url, headers=headers, data=payload)
        self.assertEqual(200, response.status_code)



if __name__ == "__main__":
    unittest.main()
