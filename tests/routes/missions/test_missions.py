import json

import requests
from models.bounty import BountyType
from models.missions import MissionType, MissionStatus, MissionRewardStatus
from tests.dummy_data_helper import DummyDataHelper
from tests.test_base import TestBase


class TestMissions(TestBase):

    def test_get_user_missions_1(self):
        bounty_id = DummyDataHelper.create_dummy_bounty(BountyType.IMAGE_UPLOAD)['id']
        DummyDataHelper.create_dummy_missions(self.default_accounts[0].address, MissionType.UPLOAD,
                                              bounty_id)

        token = self.default_tokens[0]
        headers = {"Authorization": f"Bearer {token}"}
        api_url = f"{self.url}/api/v1/missions/info?type=upload&status=ready_to_start&page=1"
        response = requests.get(api_url, headers=headers)

        self.assertEqual(200, response.status_code)
        result = json.loads(response.text)
        self.assertEqual(5, len(result['missions']))
        self.assertEqual(5, result['total_count'])

    def test_complete_upload_mission(self):
        account = self.default_accounts[0]
        bounty_id = DummyDataHelper.create_dummy_bounty(account.address,
                                                        bounty_type=BountyType.IMAGE_UPLOAD)['id']

        mission_id = DummyDataHelper.create_dummy_missions(account.address, MissionType.UPLOAD, bounty_id)

        image_id = DummyDataHelper.add_random_image(account.address, '', mission_id)

        token = self.get_token_for_account(account)
        api_url = f"{self.url}/api/v1/missions/info?type=upload&status=completed&page=1"
        headers = {"Authorization": f"Bearer {token}"}
        response = requests.get(api_url, headers=headers)

        self.assertEqual(200, response.status_code)
        result = json.loads(response.text)
        self.assertEqual(1, len(result['missions']))
        self.assertEqual(mission_id, result['missions'][0]['id'])
        self.assertEqual(1, result['total_count'])
        self.assertEqual(MissionStatus.COMPLETED, result['missions'][0]['status'])
        assert image_id is not None

    def test_ready_to_start_upload_mission(self):
        account = self.default_accounts[0]
        bounty_id = DummyDataHelper.create_dummy_bounty(BountyType.IMAGE_UPLOAD)['id']
        DummyDataHelper.create_dummy_missions(account.address, MissionType.UPLOAD, bounty_id)

        token = self.get_token_for_account(account)
        api_url = f"{self.url}/api/v1/missions/info?type=upload&status=ready_to_start&page=1"
        headers = {"Authorization": f"Bearer {token}"}
        response = requests.get(api_url, headers=headers)

        self.assertEqual(200, response.status_code)
        result = json.loads(response.text)
        self.assertEqual(5, len(result['missions']))
        self.assertEqual(MissionStatus.READY_TO_START, result['missions'][0]['status'])

    def test_upload_bounty_and_mission(self):
        DummyDataHelper.create_dummy_bounty(BountyType.IMAGE_UPLOAD)

        account = self.default_accounts[0]

        token = self.get_token_for_account(account)
        api_url = f"{self.url}/api/v1/missions/info?type=upload&status=ready_to_start&page=1"
        headers = {"Authorization": f"Bearer {token}"}
        response = requests.get(api_url, headers=headers)

        self.assertEqual(200, response.status_code)
        result = json.loads(response.text)
        self.assertEqual(5, len(result['missions']))
        self.assertEqual(5, result['total_count'])
        self.assertEqual(MissionStatus.READY_TO_START, result['missions'][0]['status'])

    def test_annotation_bounty_and_mission(self):
        entity_list_ids = [DummyDataHelper.generate_new_entity_list(self.default_accounts[0].address, 50)]

        DummyDataHelper.create_dummy_bounty(self.default_accounts[0].address, BountyType.IMAGE_ANNOTATE,
                                            number_of_annotations=1000, entity_list_ids=entity_list_ids)

        account = self.default_accounts[0]

        token = self.get_token_for_account(account)
        api_url = f"{self.url}/api/v1/missions/info?type=annotate&status=ready_to_start&page=1"
        headers = {"Authorization": f"Bearer {token}"}
        response = requests.get(api_url, headers=headers)

        self.assertEqual(200, response.status_code)
        result = json.loads(response.text)
        self.assertEqual(5, len(result['missions']))
        self.assertEqual(5, result['total_count'])
        self.assertEqual(MissionStatus.READY_TO_START, result['missions'][0]['status'])

    def test_verification_bounty_and_mission(self):
        entity_list_ids = [DummyDataHelper.generate_new_entity_list(self.default_accounts[0].address, 50)]

        DummyDataHelper.create_dummy_bounty(self.default_accounts[0].address, BountyType.IMAGE_VERIFY,
                                            number_of_verifications=1000, entity_list_ids=entity_list_ids)

        account = self.default_accounts[0]

        token = self.get_token_for_account(account)
        api_url = f"{self.url}/api/v1/missions/info?type=verify&status=ready_to_start&page=1"
        headers = {"Authorization": f"Bearer {token}"}
        response = requests.get(api_url, headers=headers)

        self.assertEqual(200, response.status_code)
        result = json.loads(response.text)
        self.assertEqual(5, len(result['missions']))
        self.assertEqual(5, result['total_count'])
        self.assertEqual(MissionStatus.READY_TO_START, result['missions'][0]['status'])

    def test_complete_annotate_mission(self):
        account = self.default_accounts[0]
        bounty_id = DummyDataHelper.create_dummy_bounty(public_address=account.address,
                                                        bounty_type=BountyType.IMAGE_ANNOTATE,
                                                        number_of_annotations=10)['id']

        mission_id = DummyDataHelper.create_dummy_missions(account.address, MissionType.ANNOTATE, bounty_id)

        image_id = DummyDataHelper.add_random_image(account.address, '', None)

        DummyDataHelper.add_metadata(image_id, ["temp"], mission_id, account)

        token = self.get_token_for_account(account)
        api_url = f"{self.url}/api/v1/missions/info?type=annotate&status=completed&page=1"
        headers = {"Authorization": f"Bearer {token}"}
        response = requests.get(api_url, headers=headers)

        self.assertEqual(200, response.status_code)
        result = json.loads(response.text)
        self.assertEqual(1, len(result['missions']))
        self.assertEqual(mission_id, result['missions'][0]['id'])
        self.assertEqual(1, result['total_count'])
        self.assertEqual(MissionStatus.COMPLETED, result['missions'][0]['status'])
        self.assertEqual(MissionRewardStatus.ready_to_pay, result["missions"][0]["reward_status"])
        assert image_id is not None
