from tests.test_base import TestBase
import requests
from datetime import datetime
from helpers.load_dummy_data import DummyDataLoader


class TestMetadataQuery(TestBase):

    def test_my_stats_query_1(self):
        token = self.get_token()

        dummy_data_loader = DummyDataLoader()
        dummy_data_loader.load_random_data3(self.acct, token, 3)

        headers = {'Authorization': 'Bearer {0}'.format(token)}
        api_url = "{0}/api/v1/stats/user?start_time=1&end_time={1}".format(self.url, datetime.timestamp(datetime.now()))
        response = requests.request("GET", api_url, headers=headers, data={})
        self.assertEqual(200, response.status_code)
