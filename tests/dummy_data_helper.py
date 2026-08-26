import json
from datetime import datetime, timedelta
from typing import List, Optional

from eth_account import Account

from commands.bounty.bounty_commands import CreateBountyCommand
from commands.entity_lists.create_entity_list_command import CreateEntityListCommand
from commands.metadata.add_new_metadata_command import AddNewMetadataCommand
from commands.metadata.verify_image_command import VerifyImageCommand
from commands.metadata.add_annotation_command import AddAnnotationCommand
from commands.metadata.add_new_image_command import AddNewImageCommand
from commands.missions.add_missions import AddNewMissionCommand, CreateMissionsFromBountyCommand
from helpers.load_dummy_data import DummyDataLoader
from models.bounty import BountyType
from models.entity_list_models import EntityListType
from models.metadata.metadata_models import EntityType
from models.missions import MissionStatus, MissionType


class DummyDataHelper:

    @staticmethod
    def add_metadata(image_id: str, tags: List[str], mission_id: str = None, account: Account = None):
        if account is None:
            account = Account.create()
        add_new_metadata_command1 = AddNewMetadataCommand(public_address=account.address, mission_id=mission_id)
        add_new_metadata_command1.input = {
            "public_address": account.address,
            "tags": tags,
            "image_id": image_id,
        }

        add_new_metadata_command1.execute()

    @staticmethod
    def mark_images_as_verified(
            public_address,
            image_ids,
            tag_up_votes: list[str],
            tag_down_votes: list[str],
            desc_up_votes: list[str],
            desc_down_votes: list[str],
    ):
        if not public_address:
            acct = Account.create()
            public_address = acct.address
        for image_id in image_ids:
            verify_image_c = VerifyImageCommand(public_address=public_address, mission_id=None)
            verify_image_c.input = {
                "public_address": public_address,
                "data": {
                    "tags": {
                        "up_votes": tag_up_votes,
                        "down_votes": tag_down_votes
                    },
                    "descriptions": {
                        "up_votes": desc_up_votes,
                        "down_votes": desc_down_votes
                    }
                },
                "image_id": image_id,
            }
            verify_image_c.execute()

    @staticmethod
    def add_bounding_box_annotations(public_address, image_id):
        add_annotation_c = AddAnnotationCommand(public_address, image_id, [{
            'type': "box", "x": 2.0, "y": 3.4, "width": 5.0, "height": 34, "tag": "abc"
        }])
        add_annotation_c.execute()

    @staticmethod
    def add_new_image(public_address: str, image_path: str, bounty: str, mission_id: str = None):
        add_new_image_c = AddNewImageCommand(public_address=public_address, image_path=image_path, bounty_name=[bounty],
                                             mission_id=mission_id)
        image_id = add_new_image_c.execute()
        assert add_new_image_c.successful is True, f"Messages: {add_new_image_c.messages}"
        return image_id

    @staticmethod
    def add_random_image(public_address: str, bounty: str = None, mission_id: str = None,
                         tags: List[str] = None) -> str:

        dummy_data_loader = DummyDataLoader()
        image_path = dummy_data_loader.generate_random_images(10, 10, 1)[0]

        add_new_image_c = AddNewImageCommand(public_address=public_address, image_path=image_path, bounty_name=[bounty],
                                             mission_id=mission_id)
        result = add_new_image_c.execute()
        assert add_new_image_c.successful is True, f"Messages: {add_new_image_c.messages}"

        if tags is not None:
            DummyDataHelper.add_metadata(result, tags)

        return result

    @staticmethod
    def create_dummy_missions(public_address: str, mission_type: MissionType = MissionType.UPLOAD,
                              bounty_id: Optional[str] = None) -> str:

        c = CreateMissionsFromBountyCommand(public_address=public_address, mission_type=mission_type,
                                            bounty_id=bounty_id, target=1)
        result = c.execute()

        assert c.successful is True, f"Messages: {c.messages}"
        return result[0]

    @staticmethod
    def get_dummy_bounty(bounty_type=BountyType.IMAGE_UPLOAD, entity_list_ids: List[str] = (),
                         number_of_verifications: int = 0, number_of_annotations: int = 0):
        data = {
            'company_name': 'cname',
            'company_description': 'cd',
            'bounty_type': bounty_type.value,
            'bounty_description': 'bd',
            'start_date': datetime.today(),
            'end_date': datetime.today() + timedelta(days=1),
            'bounty_name': 'bname',
            'tags': 'xyz,pqr',
            'sample_data_list': 'dsfjre,vgfer,eryer',
            'image_format': 'png,jpeg',
            'image_count': 100,
            'image_requirements': 'minWidth:34,minHeight:3245',
            'entity_list_name': 'test list name',
            'entity_list_ids': json.dumps(entity_list_ids),
            'number_of_verifications': number_of_verifications,
            'number_of_annotations': number_of_annotations
        }

        return data

    @staticmethod
    def create_dummy_bounty(public_address: str, bounty_type=BountyType.IMAGE_UPLOAD, image_uploads: Optional[int] = 0,
                            number_of_verifications: Optional[int] = 0,
                            number_of_annotations: Optional[int] = 0, entity_list_ids: List[str] = None) -> dict:

        if bounty_type in [BountyType.IMAGE_ANNOTATE, BountyType.IMAGE_VERIFY] and entity_list_ids is None:
            entity_list_ids = [DummyDataHelper.generate_new_entity_list(public_address, count=5)]

        images = DummyDataHelper.generate_random_images(2)
        c = CreateBountyCommand(public_address, 'cname', 'cd', bounty_type, 'bname', 'bd', datetime.today(),
                                datetime.today() + timedelta(days=1), images[0], images[1], ['x', 'y'' z'], [], '',
                                [], 'test-dataset', image_uploads, number_of_verifications, number_of_annotations,
                                entity_list_ids)
        result = c.execute()
        assert c.successful
        return result

    @staticmethod
    def generate_random_images(count=1):
        dummy_data_loader = DummyDataLoader()
        image_paths = dummy_data_loader.generate_random_images(100, 100, count)
        return image_paths

    @staticmethod
    def generate_new_entity_list(public_address: str, count=1, entity_type: EntityType = EntityType.image,
                                 entity_list_type: EntityListType = EntityListType.PRIVATE) -> str:
        doc_ids = []

        for i in range(count):
            doc_id = DummyDataHelper.add_random_image(public_address)
            doc_ids.append(doc_id)

        c = CreateEntityListCommand(public_address, entity_type, entity_list_type, doc_ids, "test", "Test")
        new_list_id = c.execute()
        return new_list_id
