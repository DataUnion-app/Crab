from tests.test_base import TestBase
import requests


class TestMetadataQuery(TestBase):

    def test_metadata_query_1(self):
        token = self.get_token()
        headers = {'Authorization': 'Bearer {0}'.format(token)}
        api_url = self.url + "/api/v1/query-metadata"
        response = requests.request("GET", api_url, headers=headers, data={})
        self.assertEqual(400, response.status_code)

    def test_metadata_query_2(self):
        token = self.get_token()
        headers = {'Authorization': 'Bearer {0}'.format(token)}
        api_url = self.url + "/api/v1/query-metadata" + "?status=AVAILABLE_FOR_TAGGING&skip_tagged=true"
        response = requests.request("GET", api_url, headers=headers, data={})
        self.assertEqual(200, response.status_code)
