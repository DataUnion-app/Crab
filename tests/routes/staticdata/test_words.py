import json
import requests

from dao.static_data_dao import StaticDataDao, WordTypes
from tests.test_base import TestBase


class TestWords(TestBase):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.static_data_dao = StaticDataDao()
        self.static_data_dao.set_config(
            self.db_user, self.password, self.db_host, "staticdata"
        )

    def setUp(self):
        self.static_data_dao.delete_all_docs()

    def tearDown(self):
        self.static_data_dao.delete_all_docs()

    def test_get_banned_words(self):
        self.static_data_dao.add_words(["1", "2", "3"], WordTypes.BANNED_WORDS.name)
        url = self.url + "/staticdata/tags?type=" + "BANNED_WORDS"
        response = requests.request("GET", url, headers={}, data=json.dumps({}))
        self.assertEqual(200, response.status_code)
        self.assertEqual(["1", "2", "3"], json.loads(response.text)["result"])

    def test_get_recommended_words(self):
        self.static_data_dao.add_words(
            ["1", "2", "3"], WordTypes.RECOMMENDED_WORDS.name
        )
        url = self.url + "/staticdata/tags?type=" + "RECOMMENDED_WORDS"
        response = requests.request("GET", url, headers={}, data=json.dumps({}))
        self.assertEqual(200, response.status_code)
        self.assertEqual(["1", "2", "3"], json.loads(response.text)["result"])
