import json
import os

import requests
from requests import Response

from models.metadata.metadata_models import Source
from tests.routes.metadata.test_metadata import TestMetadata
from tests.test_base import TestBase


class TestUploadFileFilecoin(TestBase):

    def upload_file(self, file_name: str, file_type: str) -> Response:
        file_path = os.path.join(self.dummy_data_path, "brainstem", file_name)

        acct = self.default_accounts[0]

        token = TestMetadata.get_token_for_account(acct, source=Source.brainstem)
        headers = {"Authorization": "Bearer {0}".format(token)}

        api_url = self.url + "/api/v1/upload-file"

        payload = {
            "file-type": file_type,
            "storage": "filecoin"
        }

        with open(file_path, "rb") as f:
            files = [("file", (file_name, f))]

            response = requests.request(
                "POST", api_url, headers=headers, data=payload, files=files
            )
            return response

    def test_upload_file_to_filecoin(self):
        # Upload summary file
        file_name = "summary.txt"
        file_type = "summary"
        response = self.upload_file(file_name, file_type)

        self.assertTrue(response.status_code, 200)
        data = json.loads(response.text)
        file_id = data["id"]
        self.assertTrue(file_id is not None)

        acct = self.default_accounts[0]

        # Download
        token = TestMetadata.get_token_for_account(acct, source=Source.cvat)
        headers = {"Authorization": "Bearer {0}".format(token)}
        api_url = f"{self.url}/api/v1/metadata/{file_id}/download"

        response = requests.request(
            "GET", api_url, headers=headers
        )
        import pdb; pdb.set_trace()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(file_name in response.headers["Content-Disposition"], True)