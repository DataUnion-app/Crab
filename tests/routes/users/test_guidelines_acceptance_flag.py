import unittest
import requests
import json

from dao.users_dao import UsersDao
from models.GuidelinesAcceptanceFlag import GuidelinesAcceptanceFlag
from tests.test_base import TestBase


class TestGuidelinesAcceptanceFlag(TestBase):
    def __init__(self, *args, **kwargs):
        super(TestGuidelinesAcceptanceFlag, self).__init__(*args, **kwargs)

    def test_get_guidelines_acceptance_flag1(self):
        user_dao = UsersDao()
        user_dao.set_config(self.db_user, self.password, self.db_host, "users")

        api_url = self.url + "/guidelines-acceptance"
        token = self.get_token()
        headers = {"Authorization": "Bearer {0}".format(token)}

        response = requests.request(
            "GET", api_url, headers=headers, data=json.dumps({})
        )

        self.assertEqual(200, response.status_code)
        data = json.loads(response.text)
        self.assertEqual(GuidelinesAcceptanceFlag.UNKNOWN.name, data.get("guidelines_acceptance_flag"))

    def test_get_guidelines_acceptance_flag2(self):
        user_dao = UsersDao()
        user_dao.set_config(self.db_user, self.password, self.db_host, "users")

        api_url = self.url + "/guidelines-acceptance"
        token = self.get_token()

        headers = {"Authorization": "Bearer {0}".format(token)}
        body = {"flag": "ACCEPTED"}
        response = requests.request(
            "POST", api_url, headers=headers, data=json.dumps(body)
        )

        self.assertEqual(200, response.status_code)
        data = json.loads(response.text)
        self.assertEqual("success", data.get("status"))

        flag = user_dao.get_flag(public_address=self.acct.address,
                                 flag_type="guidelines_acceptance_flag")
        self.assertEqual(GuidelinesAcceptanceFlag.ACCEPTED.name, flag)

        body = {"flag": "REJECTED"}
        response = requests.request(
            "POST", api_url, headers=headers, data=json.dumps(body)
        )

        self.assertEqual(200, response.status_code)
        data = json.loads(response.text)
        self.assertEqual("success", data.get("status"))

        flag = user_dao.get_flag(public_address=self.acct.address,
                                 flag_type="guidelines_acceptance_flag")
        self.assertEqual(GuidelinesAcceptanceFlag.REJECTED.name, flag)

        body = {"flag": "INVALID"}
        response = requests.request(
            "POST", api_url, headers=headers, data=json.dumps(body)
        )

        self.assertEqual(400, response.status_code)


if __name__ == "__main__":
    unittest.main()
