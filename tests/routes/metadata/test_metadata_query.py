from tests.test_base import TestBase
import requests
import json


class TestMetadataQuery(TestBase):
    def test_metadata_query_1(self):
        token = self.get_token()
        headers = {"Authorization": "Bearer {0}".format(token)}
        api_url = self.url + "/api/v1/query-metadata"
        response = requests.request(
            "POST", api_url, headers=headers, data=json.dumps({})
        )
        self.assertEqual(400, response.status_code)

    def test_metadata_query_2(self):
        token = self.get_token()
        headers = {"Authorization": "Bearer {0}".format(token)}
        api_url = self.url + "/api/v1/query-metadata"
        data = {
            "status": "VERIFIABLE",
            "fields": ["image_id", "tag_data", "description"]
        }
        response = requests.request(
            "POST", api_url, headers=headers, data=json.dumps(data)
        )
        self.assertEqual(200, response.status_code)

    def test_metadata_query_3(self):
        token = self.get_token()
        headers = {"Authorization": "Bearer {0}".format(token)}
        api_url = self.url + "/api/v1/query-metadata"
        data = {
            "status": "VERIFIABLE",
            "type": "BoundingBox",
            "fields": ["image_id", "tag_data", "description"]
        }
        response = requests.request(
            "POST", api_url, headers=headers, data=json.dumps(data)
        )
        self.assertEqual(200, response.status_code)

    def test_metadata_query_4(self):
        token = self.get_token()
        headers = {"Authorization": "Bearer {0}".format(token)}
        api_url = self.url + "/api/v1/query-metadata"
        data = {
            "status": "VERIFIABLE",
            "type": "Anonymization",
            "fields": ["image_id", "tag_data", "description"],
            "tags": ["test-tag"]
        }
        response = requests.request(
            "POST", api_url, headers=headers, data=json.dumps(data)
        )
        self.assertEqual(200, response.status_code)
