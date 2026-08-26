from tests.test_base import TestBase
import requests
import json


class TestChallengeQuery(TestBase):
    def test_challenge_get_query(self):
        api_url = self.url + "/api/v1/challenges"
        response = requests.request("GET", api_url, data=json.dumps({}))
        self.assertEqual(200, response.status_code)

    def test_challenge_upload_query(self):
        token = self.get_token()
        headers = {"Authorization": "Bearer {0}".format(token)}
        api_url = self.url + "/api/v1/challenges/upload"
        data = {
            "name": "Image Challenge Query Test",
            "status": "RUNNING",
            "description": "Query Test Challenge Description",
            "rules": "Sample Rules",
        }
        response = requests.request(
            "POST", api_url, headers=headers, data=json.dumps(data)
        )
        self.assertEqual(200, response.status_code)
