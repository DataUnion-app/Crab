from datetime import datetime, timedelta

from commands.rewards.calculate_reward import CalculateRewardCommand
from models.metadata.metadata_models import EntityType, Source
from models.rewards.rewards_model import ClaimRewardErrorMessages
from tests.dummy_data_helper import DummyDataHelper
from tests.test_base import TestBase
from commands.rewards.claim_reward_command import ClaimRewardCommand
from unittest.mock import MagicMock
import time_machine


class TestClaimRewardsCommand(TestBase):

    def test_nothing_to_claim(self):
        address = self.default_accounts[0].address
        c = ClaimRewardCommand(address, Source.default, EntityType.image)
        c.transfer = MagicMock(return_value='1' * 64)
        result = c.execute()
        self.assertFalse(c.successful)
        self.assertIsNone(result)
        self.assertListEqual(c.messages, [ClaimRewardErrorMessages.ZERO_AMOUNT])

    def test_claim_rewards(self):
        account = self.default_accounts[0]
        address = self.default_accounts[0].address
        with time_machine.travel(datetime.utcnow() - timedelta(days=1)):
            DummyDataHelper.add_random_image(account.address, 'x', None)

        c = ClaimRewardCommand(address, Source.default, EntityType.image)
        c.transfer = MagicMock(return_value='1' * 64)
        result = c.execute()
        self.assertTrue(c.successful)
        self.assertEqual('1' * 64, result)

    def test_claimable_rewards_for_today(self):
        account = self.default_accounts[0]
        address = self.default_accounts[0].address

        DummyDataHelper.add_random_image(account.address, 'x', None)

        c = CalculateRewardCommand(address, Source.default, EntityType.image, 0)
        result = c.execute()
        self.assertTrue(c.successful)
        self.assertEqual((10 ** 18) / 10, result['amount'])

        claim_date = datetime.strftime(datetime.utcnow(), "%d-%m-%Y")
        self.assertEqual('01-01-2021', result['start_date'])
        self.assertEqual(claim_date, result['end_date'])
        self.assertEqual(Source.default, result['app'])

    def test_claimable_rewards_for_today_after_claiming(self):
        account = self.default_accounts[0]
        address = self.default_accounts[0].address

        DummyDataHelper.add_random_image(account.address, 'x', None)

        with time_machine.travel(datetime.utcnow() - timedelta(days=1)):
            DummyDataHelper.add_random_image(account.address, 'x', None)

        c = CalculateRewardCommand(address, Source.default, EntityType.image, 0)
        result = c.execute()
        self.assertTrue(c.successful)
        self.assertEqual((10 ** 18) / 10 * 2, result['amount'])

        claim_date = datetime.strftime(datetime.utcnow(), "%d-%m-%Y")
        self.assertEqual('01-01-2021', result['start_date'])
        self.assertEqual(claim_date, result['end_date'])
        self.assertEqual(Source.default, result['app'])

        c = ClaimRewardCommand(address, Source.default, EntityType.image)
        c.transfer = MagicMock(return_value=(10 ** 18) / 10)
        result = c.execute()
        self.assertTrue(c.successful)
        self.assertEqual((10 ** 18) / 10, result)

        c = CalculateRewardCommand(address, Source.default, EntityType.image, 0)
        result = c.execute()
        self.assertTrue(c.successful)
        self.assertEqual((10 ** 18) / 10, result['amount'])

        claim_date = datetime.strftime(datetime.utcnow(), "%d-%m-%Y")
        self.assertEqual(claim_date, result['start_date'])
        self.assertEqual(claim_date, result['end_date'])
        self.assertEqual(Source.default, result['app'])

    def test_claim_reward_if_already_claimed(self):
        account = self.default_accounts[0]
        with time_machine.travel(datetime.utcnow() - timedelta(days=2)):
            DummyDataHelper.add_random_image(account.address, 'x', None)

        claim1 = ClaimRewardCommand(account.address, Source.default, EntityType.image)
        claim1.transfer = MagicMock(return_value='1' * 64)
        claim1.execute()
        self.assertTrue(claim1.successful)

        claim2 = ClaimRewardCommand(self.acct.address, Source.default, EntityType.image)
        claim2.transfer = MagicMock(return_value='1' * 64)
        result2 = claim2.execute()
        self.assertFalse(claim2.successful)
        self.assertIsNone(result2)
        self.assertListEqual(claim2.messages, ['Reward amount is 0'])
