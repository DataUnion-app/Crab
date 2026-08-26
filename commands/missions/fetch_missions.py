from datetime import datetime, timedelta

from commands.missions.add_missions import CreateMissionsFromBountyCommand
from dao.missions_dao import missions_dao
from dao.bounty_dao import bounty_dao
from dao.entity_list_dao import entity_list_dao
from commands.base_command import BaseCommand
from models.missions import MissionType, MissionStatus
from typing import List

from utils.utils import DEFAULT_DATETIME_FORMAT_STRING


class FetchUserMissionsInformationCommand(BaseCommand):
    def __init__(self, public_address, mission_types: List[MissionType], statuses: List[MissionStatus], page: int = 1,
                 bounty_id: str = None,
                 sort_by: str = "created_at", sort_direction: str = "desc"):
        super().__init__(public_address)
        self.statuses = statuses
        self.mission_types = mission_types
        self.page = page
        self.sort_by = sort_by
        self.sort_direction = sort_direction
        self.bounty_id = bounty_id

    def execute(self):
        mission_data = []
        result = missions_dao.get_missions_for_user(self.public_address, self.mission_types, self.statuses, self.page,
                                                    sort_by=self.sort_by, sort_direction=self.sort_direction,
                                                    bounty_id=self.bounty_id)

        if MissionStatus.READY_TO_START in self.statuses:
            for mission_type in self.mission_types:
                filtered_result = list(filter(lambda x: x['type'] == mission_type, result))
                if MissionStatus.READY_TO_START not in [r['status'] for r in filtered_result]:
                    CreateMissionsFromBountyCommand(self.public_address, mission_type,
                                                    bounty_id=self.bounty_id).execute()

        result = missions_dao.get_missions_for_user(self.public_address, self.mission_types, self.statuses,
                                                    self.page, sort_by=self.sort_by, sort_direction=self.sort_direction,
                                                    bounty_id=self.bounty_id)
        count = missions_dao.get_mission_count_for_user(self.public_address, self.mission_types, self.statuses,
                                                        bounty_id=self.bounty_id)

        for mission in result:
            progress = get_mission_progress(mission)

            end_date = mission.get('end_date')
            if end_date is None:
                d = timedelta(days=365)
                end_date = datetime.fromisoformat(mission['created_at']) + d
                end_date = end_date.strftime(DEFAULT_DATETIME_FORMAT_STRING)

            mission_info = {
                'status': mission['status'],
                'criteria': mission['criteria'],
                'id': mission['_id'],
                'type': mission['type'],
                'progress': progress,
                'level': mission['level'],
                'title': mission['title'],
                'description': mission['description'],
                'bounty_id': mission["bounty_id"],
                'end_date': end_date,
                'reward_status': mission.get("reward_status")
            }

            entity_ids = mission.get('entity_ids')
            if entity_ids:
                mission_info['entity_ids'] = entity_ids

            mission_data.append(mission_info)

        self.successful = True
        return {"total_count": count, "missions": mission_data}

class FetchUserMissionsOverViewCommand(BaseCommand):
    def __init__(self, public_address, mission_types: List[MissionType], statuses: List[MissionStatus], page: int = 1,
                 bounty_id: str = None,
                 sort_by: str = "created_at", sort_direction: str = "desc"):
        super().__init__(public_address)
        self.statuses = statuses
        self.mission_types = mission_types
        self.page = page
        self.sort_by = sort_by
        self.sort_direction = sort_direction
        self.bounty_id = bounty_id

    def execute(self):
        mission_data = []
        result = missions_dao.get_missions_for_user(self.public_address, self.mission_types, self.statuses, self.page,
                                                    sort_by=self.sort_by, sort_direction=self.sort_direction,
                                                    bounty_id=self.bounty_id)

        if MissionStatus.READY_TO_START in self.statuses:
            for mission_type in self.mission_types:
                filtered_result = list(filter(lambda x: x['type'] == mission_type, result))
                if MissionStatus.READY_TO_START not in [r['status'] for r in filtered_result]:
                    CreateMissionsFromBountyCommand(self.public_address, mission_type,
                                                    bounty_id=self.bounty_id).execute()

        result = missions_dao.get_missions_for_user(self.public_address, self.mission_types, self.statuses,
                                                    self.page, sort_by=self.sort_by, sort_direction=self.sort_direction,
                                                    bounty_id=self.bounty_id)
        count = missions_dao.get_mission_count_for_user(self.public_address, self.mission_types, self.statuses,
                                                        bounty_id=self.bounty_id)

        for mission in result:
            progress = get_mission_progress(mission)

            end_date = mission.get('end_date')
            if end_date is None:
                d = timedelta(days=365)
                end_date = datetime.fromisoformat(mission['created_at']) + d
                end_date = end_date.strftime(DEFAULT_DATETIME_FORMAT_STRING)

            mission_info = {
                'status': mission['status'],
                'criteria': mission['criteria'],
                'id': mission['_id'],
                'type': mission['type'],
                'progress': progress,
                'level': mission['level'],
                'title': mission['title'],
                'description': mission['description'],
                'bounty_id': mission["bounty_id"],
                'end_date': end_date,
                'reward_status': mission.get("reward_status")
            }

            entity_ids = mission.get('entity_ids')
            result = bounty_dao.get_doc_by_id(mission["bounty_id"])
            entity_list_id = result['entity_list_id']
            
            entity_list = entity_list_dao.get_doc_by_id(entity_list_id)
            all_entities = set(entity_list["entity_ids"])
            accepted_entities = set(entity_list.get("accepted_image_ids", []))
            accepted_entity_count = len(set(all_entities) & set(accepted_entities))

            rejected_entities = set(entity_list.get("rejected_image_ids", []))
            rejected_entity_count = len(set(all_entities) & set(rejected_entities))

            mission_info['accepted_count'] = accepted_entity_count
            mission_info['returned_count'] = rejected_entity_count

            if entity_ids:
                mission_info['entity_ids'] = entity_ids

            mission_data.append(mission_info)

        self.successful = True
        return {"total_count": count, "missions": mission_data}

class GetMissionByIdCommand(BaseCommand):

    def __init__(self, public_address: str, mission_id: str):
        super(GetMissionByIdCommand, self).__init__(public_address)
        self.mission_id = mission_id

    def execute(self):
        document = missions_dao.get_mission_details_for_user(self.public_address, self.mission_id)
        if document is None:
            self.successful = False
            self.messages.append(f"Mission with id [{self.mission_id}] not found")
            return

        end_date = document.get('end_date')
        if end_date is None:
            d = timedelta(days=365)
            end_date = datetime.strptime(document['created_at'], DEFAULT_DATETIME_FORMAT_STRING) + d
            end_date = end_date.strftime(DEFAULT_DATETIME_FORMAT_STRING)

        self.successful = True
        mission_information = {
            'id': document['_id'],
            'created_at': document['created_at'],
            'criteria': document['criteria'],
            'created_by': document['public_address'],
            'status': document['status'],
            'description': document['description'],
            'level': document['level'],
            'image': document.get('image'),
            'type': document['type'],
            'title': document['title'],
            'progress': get_mission_progress(document),
            'bounty_id': document["bounty_id"],
            'end_date': end_date
        }

        entity_ids = document.get('entity_ids')
        if entity_ids:
            mission_information['entity_ids'] = entity_ids

        return mission_information


def get_mission_progress(mission: dict) -> any:
    progress = None
    if mission['type'] == MissionType.UPLOAD:
        progress = len(mission['progress']['upload_ids'])
    elif mission['type'] == MissionType.ANNOTATE:
        progress = len(mission['progress']['annotation_ids'])
    elif mission['type'] == MissionType.VERIFY:
        progress = len(mission['progress']['verification_ids'])

    return progress
