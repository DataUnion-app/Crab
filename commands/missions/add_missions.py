from typing import Optional

from dao.missions_dao import missions_dao
from commands.base_command import BaseCommand
from dao.bounty_dao import bounty_dao
from models.bounty import BountyType, BountyStatus
from models.missions import MissionType, MissionStatus, MissionRewardStatus


class AddNewMissionCommand(BaseCommand):
    MAX_DESCRIPTION_LENGTH = 2000

    def __init__(self, mission):
        super().__init__()
        self.new_mission = mission

    def execute(self):
        mission_id = missions_dao.add_new_mission(self.new_mission)
        self.successful = True
        return mission_id


class CreateMissionsFromBountyCommand(BaseCommand):

    def __init__(self, public_address: str, mission_type: MissionType, bounty_id: Optional[str] = None,
                 target: Optional[int] = 10):
        super(CreateMissionsFromBountyCommand, self).__init__(public_address)
        self.mission_type = mission_type
        self.bounty_id = bounty_id
        # A number indicating number of annotations/uploads/verifications a user must perform in the mission.
        self.target = target

    def execute(self):
        # List of mission ids
        result = []

        bounty_type = None
        if self.mission_type == MissionType.UPLOAD:
            bounty_type = BountyType.IMAGE_UPLOAD
        elif self.mission_type == MissionType.VERIFY:
            bounty_type = BountyType.IMAGE_VERIFY
        elif self.mission_type == MissionType.ANNOTATE:
            bounty_type = BountyType.IMAGE_ANNOTATE

        for i in range(5):
            if self.bounty_id:
                bounty_information = bounty_dao.get_doc_by_id(self.bounty_id)
            else:
                bounty_information = bounty_dao.search_bounty(BountyStatus.IN_PROGRESS, bounty_type, 1)[0]
            mission_details = {
                'type': self.mission_type,
                'public_address': self.public_address,
                'uploads': [],
                "criteria": {
                    "target": self.target,
                },
                "progress": {
                    'upload_ids': [],
                    'annotation_ids': [],
                    'verification_ids': []
                },
                'level': 1,
                # TODO: somehow manage to store the image information from the bounty. Complicated to do.
                'title': bounty_information['bounty_name'],
                'description': bounty_information['bounty_description'],
                'status': MissionStatus.READY_TO_START,
                'bounty_id': bounty_information["_id"],
                'end_date': bounty_information['end_date'],
                'reward_status': MissionRewardStatus.not_ready_to_be_paid
            }

            if "missions" not in bounty_information:
                bounty_information["missions"] = []
            if "missions_count" not in bounty_information:
                bounty_information["missions_count"] = 0
            else:
                bounty_information["missions_count"] = bounty_information["missions_count"] + 1

            if self.mission_type in [MissionType.VERIFY, MissionType.ANNOTATE]:

                '''
                Only applicable for bounties which are restricted to be worked only on certain entities.
                e.g. Annotations to be added only on a certain set of images. The list of image ids is stored in
                bounty_information['entity_ids'].
                Check if user has been allocated some verifications/annotations from 'entity_ids'.
                What has been already allocated to user is stored as follows:
                    bounty_information['per_user_allocated_entity_ids_index'][user_address] = [<entity_ids>]
                    e.g.
                    bounty_information['per_user_allocated_entity_ids_index']['0x1245534534'] = ['abc', '123']
                
                Here, the new mission should exclude the already allocated entity ids and ideally allocate the least
                allocated entities for the mission overall. The overall goal is to uniformly distribute entities among 
                users and maximize the probability of getting a bounty towards completion.
                
                Step 1: Check what has been already allocated to the user
                Step 2: Find what is remaining to be allocated to user
                Step 3: Take a subset of least allocated entities and assign is to mission.
                Step 4: Update allocations
                
                '''
                # Step 1
                if self.public_address not in bounty_information['per_user_allocated_entity_ids_index']:
                    bounty_information['per_user_allocated_entity_ids_index'][self.public_address] = []
                already_allocated = bounty_information['per_user_allocated_entity_ids_index'][self.public_address]

                # Step 2
                '''
                e.g.
                
                already_allocated = ['abc']
                
                remaining_allocations = {
                    'xyz' : 0,
                    'pqr': 123
                    }
                '''
                remaining_allocations = CreateMissionsFromBountyCommand.without_keys(
                    bounty_information['entity_id_allocations'],
                    already_allocated)
                # Step 3
                least_allocated_entities = sorted(remaining_allocations.items(), key=lambda x: x[1], reverse=False)[
                                           0:self.target]
                least_allocated_entities = [i[0] for i in least_allocated_entities]

                if len(least_allocated_entities) == 0:
                    self.successful = False
                    self.messages.append(
                        f"No entity allocation left for user in the bounty [{bounty_information['_id']}]")
                    return

                # Required to re-assign the target based on actual available entities
                mission_details['criteria']["target"] = len(least_allocated_entities)

                # Step 4
                mission_details['entity_ids'] = least_allocated_entities
                bounty_information['per_user_allocated_entity_ids_index'][
                    self.public_address] += least_allocated_entities
                for entity_id in least_allocated_entities:
                    bounty_information['entity_id_allocations'][entity_id] += 1

            mission_id = missions_dao.add_new_mission(mission_details)
            result.append(mission_id)
            bounty_information["missions"].append(mission_id)

            bounty_dao.update_doc(bounty_information["_id"], bounty_information)

        self.successful = True
        return result

    @staticmethod
    def without_keys(d, keys):
        return {x: d[x] for x in d if x not in keys}
