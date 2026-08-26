import json
import os

import requests
from requests import Response

from models.metadata.metadata_models import Source
from tests.routes.metadata.test_metadata import TestMetadata
from tests.test_base import TestBase


class TestUploadFile(TestBase):
    def test_upload_brainstem_files(self):
        # Upload summary file
        file_name = "summary.txt"
        file_type = "summary"
        response = self.upload_brainstem_file(file_name, file_type)

        self.assertTrue(response.status_code, 200)
        data = json.loads(response.text)
        file_id = data["id"]
        self.assertTrue(file_id is not None)

        # Upload over-chunk file
        file_name = "OverChunk.txt"
        file_type = "over_chunk"
        response = self.upload_brainstem_file(file_name, file_type)

        self.assertTrue(response.status_code, 200)
        data = json.loads(response.text)
        file_id = data["id"]
        self.assertTrue(file_id is not None)

    def test_upload_brainstem_hbr_rr_file(self):
        # Upload hbr_rr file
        file_name = "HBR_RR.txt"
        file_type = "hbr_rr"
        response = self.upload_brainstem_file(file_name, file_type)

        self.assertTrue(response.status_code, 200)
        data = json.loads(response.text)
        file_id = data["id"]
        self.assertTrue(file_id is not None)

    def test_upload_wedadanation_usermetadata_file(self):
        # Upload hbr_rr file
        file_name = "user_metadata.json"
        file_type = "user_metadata"
        response = self.upload_wedatanation_file(file_name, file_type)

        self.assertTrue(response.status_code, 200)
        data = json.loads(response.text)
        file_id = data["id"]
        self.assertTrue(file_id is not None)

        response = self.upload_wedatanation_file(file_name, file_type)
        data = json.loads(response.text)
        new_file_id = data["id"]

        self.assertNotEqual(new_file_id, file_id)
        acct = self.default_accounts[0]

        token = TestMetadata.get_token_for_account(acct, source=Source.cvat)
        headers = {"Authorization": "Bearer {0}".format(token)}
        api_url = f"{self.url}/api/v1/metadata/query-view?design-doc=wedatanation&view=user-metadata&query-type=user_id"

        response = requests.request(
            "GET", api_url, headers=headers,
            data=json.dumps({})
        )

        self.assertEqual(response.status_code, 200)
        data = json.loads(response.text)
        self.assertEqual(len(data['result']), 1)

    def test_upload_ncight_usermetadata_file(self):
        # Upload hbr_rr file
        file_name = "user_metadata.json"
        file_type = "user_metadata"
        response = self.upload_ncight_file(file_name, file_type)

        self.assertTrue(response.status_code, 200)
        data = json.loads(response.text)
        file_id = data["id"]
        self.assertTrue(file_id is not None)

    def test_upload_ncight_image_file(self):
        # Upload hbr_rr file
        file_name = "img.png"
        file_type = "image"
        response = self.upload_ncight_file(file_name, file_type)

        self.assertTrue(response.status_code, 200)
        data = json.loads(response.text)
        file_id = data["id"]
        self.assertTrue(file_id is not None)
        api_url = self.url + "/api/v1/metadata/query"
        headers = {"Authorization": "Bearer {0}".format(self.get_token())}

        response = requests.request(
            "POST", api_url, headers=headers,
            data=json.dumps({'image_ids': [file_id], 'annotations': ['ncight_user_metadata']})
        )
        data = json.loads(response.text)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(data["status"], "success")
        self.assertListEqual(data["result"]["ncight_user_metadata"],
                             [{
                                 "image_id": file_id,
                                 "value":
                                     {"data": {"surgery_date": "2020-01-01", "patient_id": "1234", "surgeon_id": 123,
                                               "type_of_surgery": "123abc"}}

                             }
                             ])

    def test_upload_cvat_image_file_with_anntation(self):
        acct = self.default_accounts[0]

        token = TestMetadata.get_token_for_account(acct, source=Source.cvat)
        headers = {"Authorization": "Bearer {0}".format(token)}

        api_url = self.url + "/api/v1/upload-file"

        payload = {
            "annotations": """[
                {
                    "type": "cvat_id",
                    "cvat_image_id": "1234"
                }
            ]"""
        }
        image_path = os.path.join(self.dummy_data_path, "sample.png")

        with open(image_path, "rb") as img:
            files = [("file", ("sample.png", img, "image/jpg"))]

            response = requests.request(
                "POST", api_url, headers=headers, data=payload, files=files
            )
            self.assertTrue(response.status_code, 200)
            data = json.loads(response.text)
            image_id = data["id"]
            self.assertTrue(image_id is not None)

        api_url = self.url + "/api/v1/metadata/query"
        headers = {"Authorization": "Bearer {0}".format(self.get_token())}
        response = requests.request(
            "POST", api_url, headers=headers,
            data=json.dumps({'image_ids': [image_id], 'annotations': ['cvat_id']})
        )
        data = json.loads(response.text)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(data["status"], "success")
        self.assertListEqual(data["result"]["cvat_id"],
                             [{
                                 "image_id": image_id,
                                 "value": {
                                     "cvat_image_id": "1234"
                                 }
                             }
                             ])

    def upload_brainstem_file(self, file_name: str, file_type: str) -> Response:
        file_path = os.path.join(self.dummy_data_path, "brainstem", file_name)

        acct = self.default_accounts[0]

        token = TestMetadata.get_token_for_account(acct, source=Source.brainstem)
        headers = {"Authorization": "Bearer {0}".format(token)}

        api_url = self.url + "/api/v1/upload-file"

        payload = {
            "file-type": file_type
        }

        with open(file_path, "rb") as f:
            files = [("file", (file_name, f))]

            response = requests.request(
                "POST", api_url, headers=headers, data=payload, files=files
            )
            return response

    def upload_ncight_file(self, file_name: str, file_type: str) -> Response:
        file_path = os.path.join(self.dummy_data_path, "ncight", file_name)

        acct = self.default_accounts[0]

        token = TestMetadata.get_token_for_account(acct, source=Source.ncight)
        headers = {"Authorization": "Bearer {0}".format(token)}

        api_url = self.url + "/api/v1/upload-file"

        payload = {
            "file-type": file_type,
            "annotations": """[
                       {
                           "type": "ncight_user_metadata",
                           "data": {"surgery_date": "2020-01-01", "patient_id":"1234", "surgeon_id": 123,
                            "type_of_surgery": "123abc"}
                       }
                   ]"""
        }

        with open(file_path, "rb") as f:
            files = [("file", (file_name, f))]

            response = requests.request(
                "POST", api_url, headers=headers, data=payload, files=files
            )
            return response

    def upload_wedatanation_file(self, file_name: str, file_type: str) -> Response:
        file_path = os.path.join(self.dummy_data_path, "wedatanation", file_name)

        acct = self.default_accounts[0]

        token = TestMetadata.get_token_for_account(acct, source=Source.wedatanation)
        headers = {"Authorization": "Bearer {0}".format(token)}

        api_url = self.url + "/api/v1/upload/user-data"

        payload = {
            "type": file_type
        }

        with open(file_path, "rb") as f:
            files = [("file", (file_name, f))]

            response = requests.request(
                "POST", api_url, headers=headers, data=payload, files=files
            )
            return response
