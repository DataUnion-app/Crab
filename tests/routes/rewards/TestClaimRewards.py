from datetime import datetime, timedelta

import time_machine

from tests.dummy_data_helper import DummyDataHelper
from tests.test_base import TestBase
import json
import requests


class TestMetadataAnnotate(TestBase):

    def test_claim_upload_reward(self):
        headers = {"Authorization": "Bearer {0}".format(self.get_token())}
        api_url = self.url + '/api/v1/rewards/claim'

        data = {
            "entity_type": "image"
        }

        response = requests.request("POST", api_url, headers=headers, data=json.dumps(data))
        self.assertEqual(400, response.status_code)

    def test_claim_reward_2(self):
        account = self.default_accounts[0]
        token = self.default_tokens[0]
        with time_machine.travel(datetime.utcnow() - timedelta(days=1)):
            DummyDataHelper.add_random_image(account.address, 'x', None)

        headers = {"Authorization": "Bearer {0}".format(token)}
        api_url = self.url + '/api/v1/rewards/?entity_type=image'
        response = requests.request("GET", api_url, headers=headers, data=json.dumps({}))

        self.assertEqual(200, response.status_code)

        api_url = self.url + '/api/v1/rewards/claim'

        data = {
            "entity_type": "image"
        }

        response = requests.request("POST", api_url, headers=headers, data=json.dumps(data))
        self.assertEqual(200, response.status_code)

        api_url = self.url + '/api/v1/rewards/?entity_type=image'
        response = requests.request("GET", api_url, headers=headers, data=json.dumps({}))
        self.assertEqual(400, response.status_code)
