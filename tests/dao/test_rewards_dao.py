import unittest

from models.metadata.metadata_models import EntityType
from tests.test_base import TestBase
from datetime import datetime


class TestRewardsDao(TestBase):

    def test_claim_count_0(self):
        address = self.default_accounts[0].address
        count = self.rewards_dao.get_claim_count(datetime.now(), address)
        self.assertEqual(0, count)

    def test_claim_count_1(self):
        address = self.default_accounts[0].address
        claim_id = self.rewards_dao.create_new_claim(address, datetime.now(), datetime.now(), EntityType.image)
        self.rewards_dao.update_claim_as_successful(claim_id, '1' * 64)

        count = self.rewards_dao.get_claim_count(datetime.now(), address)
        self.assertEqual(1, count)

    def test_claim_count_2(self):
        address = self.default_accounts[0].address
        claim_id = self.rewards_dao.create_new_claim(address, datetime.now(), datetime.now(), EntityType.image)
        self.rewards_dao.update_claim_as_successful(claim_id, '1' * 64)

        claim_id = self.rewards_dao.create_new_claim(address, datetime.now(), datetime.now(), EntityType.image)
        self.rewards_dao.update_claim_as_successful(claim_id, '2' * 64)

        count = self.rewards_dao.get_claim_count(datetime.now(), address)
        self.assertEqual(2, count)


if __name__ == "__main__":
    unittest.main()
