from tests.test_base import TestBase
import requests
import json


class TestHandshake(TestBase):

    def test_create_handshake(self):
        token = self.get_token()
        headers = {"Authorization": "Bearer {0}".format(token)}
        api_url = self.url + "/api/v1/handshake/create"
        data = {
            "latitude": "1232",
            "longitude": "32223",
            "initiated_by" : "address_test1"
        }
        response = requests.request(
            "POST", api_url, headers=headers, data=json.dumps(data)
        )
        self.assertEqual(200, response.status_code)
        self.assertIn('id', response.json())

    def test_get_all_handshake(self):
        self.test_create_handshake()
        api_url = self.url + "/api/v1/handshake/all"
        response = requests.request("GET", api_url, data=json.dumps({}))

        self.assertEqual(200, response.status_code)
        self.assertNotEqual(0, len(response.json()['result']))
