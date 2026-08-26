from datetime import datetime, timedelta

from commands.bounty.bounty_commands import CreateBountyCommand
from models.bounty import BountyType, BountyStatus
from tests.dummy_data_helper import DummyDataHelper
from tests.test_base import TestBase


class TestBountyCommands(TestBase):

    def test_create_bounty_1(self):
        start_date = datetime.utcnow()
        end_date = datetime.utcnow() + timedelta(days=1)

        images = DummyDataHelper.generate_random_images(2)

        b = CreateBountyCommand(self.default_accounts[0].address, 'c', 'd', BountyType.IMAGE_UPLOAD, 'n', 'bd',
                                start_date, end_date, images[0], images[1], [], [], '', [], 'test-dataset',
                                100)
        bounty_id = b.execute()['id']
        self.assertTrue(b.successful)

        status = self.bounty_dao.get_doc_by_id(bounty_id)['status']

        self.assertEqual(BountyStatus.IN_PROGRESS, status)

    def test_create_bounty_2(self):
        start_date = datetime.utcnow() + timedelta(days=5)
        end_date = datetime.utcnow() + timedelta(days=10)

        images = DummyDataHelper.generate_random_images(2)

        b = CreateBountyCommand(self.default_accounts[0].address, 'c', 'd', BountyType.IMAGE_UPLOAD, 'n', 'bd',
                                start_date, end_date, images[0], images[1], [], [], '', [], 'list-name',
                                100)
        result = b.execute()
        self.assertTrue(b.successful)
        bounty_id = result['id']
        status = self.bounty_dao.get_doc_by_id(bounty_id)['status']

        self.assertEqual(BountyStatus.CREATED, status)
