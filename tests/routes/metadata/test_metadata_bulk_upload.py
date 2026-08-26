import unittest
from eth_account import Account
from dao.metadata_dao import ImageMetadataDao
import json
import os
import shutil
import requests

from models.metadata.annotations.annotation_type import AnnotationType
from utils.get_project_dir import get_project_root
from tests.test_base import TestBase


class TestMetadataBulkUpload(TestBase):
    def __init__(self, *args, **kwargs):
        self.db_host = ""
        self.data_dir = os.path.join(get_project_root(), "data")
        self.dummy_data_path = os.path.join(get_project_root(), "tests", "data")
        super(TestMetadataBulkUpload, self).__init__(*args, **kwargs)

    def test_metadata_to_image(self):
        acct = Account.create()
        token = TestMetadataBulkUpload.get_token_for_account(acct)
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
        data = {"image_id": image_id, "tags": ["t1", "t2"]}
        response = requests.request(
            "POST", api_url, headers=headers, data=json.dumps(data)
        )
        self.assertTrue(response.status_code, 200)

        result = self.image_metadata_dao.get_doc_by_id(image_id)["annotations"]
        tag_annotations = [x for x in result if x['type'] == AnnotationType.TextTag]

        self.assertEqual(1, len(tag_annotations))
        self.assertEqual(["t1", "t2"], tag_annotations[0].get("tags"))
        self.assertEqual(acct.address, tag_annotations[0].get("public_address"))

        acct2 = Account.create()
        api_url = self.url + "/api/v1/annotate"
        token2 = TestMetadataBulkUpload.get_token_for_account(acct2)
        headers2 = {"Authorization": "Bearer {0}".format(token2)}
        data2 = {"image_id": image_id, "tags": ["u1", "u2"]}
        response2 = requests.request(
            "POST", api_url, headers=headers2, data=json.dumps(data2)
        )
        self.assertTrue(response2.status_code, 200)

        result = self.image_metadata_dao.get_doc_by_id(image_id)["annotations"]

        tag_annotations = [x for x in result if x['type'] == AnnotationType.TextTag]

        self.assertEqual(2, len(tag_annotations))
        self.assertEqual(["u1", "u2"], tag_annotations[1].get("tags"))
        self.assertEqual(acct2.address, tag_annotations[1].get("public_address"))

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


if __name__ == "__main__":
    unittest.main()
