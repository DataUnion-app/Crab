from typing import List

from config import config
from dao.base_dao import BaseDao
from datetime import datetime

from models.missions import MissionType, MissionStatus, MissionRewardStatus


class MissionsDao(BaseDao):

    def __init__(self):
        super(MissionsDao, self).__init__()
        self.id_prefix = 'mission'

    def add_new_mission(self, mission):
        doc_id = self.generate_new_doc_id()
        mission["updated_at"] = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.%f%Z")
        mission["created_at"] = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.%f%Z")

        result = self.save(
            doc_id,
            mission,
        )
        return result['id']

    def get_all_missions(self):
        selector = {"selector": {"_id": {"$gt": None}}}

        result = self.query_data(selector)["result"]
        return result

    def get_mission_details_by_id(self, mission_id: str):
        selector = {"selector": {"_id": mission_id}}
        result = self.query_data(selector)["result"]
        if len(result) != 1:
            return None
        return result[0]

    def get_mission_details_for_user(self, public_address: str, mission_id: str):
        selector = {"selector": {"_id": mission_id, 'public_address': public_address}}
        result = self.query_data(selector)["result"]
        if len(result) == 1:
            return result[0]
        else:
            return None

    def get_missions_by_public_address(self, public_address: str):
        selector = {"selector": 
        {'public_address': public_address},
        "fields" : ["_id", "title", "status", "progress.upload_ids", "bounty_id" ]}
        result = self.query_data(selector)["result"]
        if len(result) > 0:
            return result
        else:
            return None

    def get_missions_for_user(self, public_address: str, mission_types: List[MissionType],
                              mission_statuses: List[MissionStatus],
                              page: int, bounty_id: str = None, sort_by: str = "created_at",
                              sort_direction: str = "desc"):
        selector = {"selector": {"type": {"$in": mission_types},
                                 'public_address': public_address, 'status': {"$in": mission_statuses}
                                 },
                    'skip': self.page_size * (page - 1),
                    'sort': [{sort_by: sort_direction}],
                    'limit': self.page_size}

        if bounty_id is not None:
            selector["selector"]["bounty_id"] = bounty_id

        return self.query_data(selector)["result"]

    def get_mission_count_for_user(self, public_address: str, mission_types: List[MissionType],
                                   mission_statuses: List[MissionStatus], bounty_id: str = None) -> int:
        selector = {"selector": {"type": {"$in": mission_types},
                                 'public_address': public_address, 'status': {"$in": mission_statuses}
                                 },
                    "fields": ["_id"]
                    }

        if bounty_id is not None:
            selector["selector"]["bounty_id"] = bounty_id

        result = self.query_all(selector)
        return len(result)

    def update_progress(self, mission_id: str, annotation_ids: list = [], upload_ids: list = [],
                        verification_ids: list = []):
        doc = self.get_doc_by_id(mission_id)
        doc["updated_at"] = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.%f%Z")
        doc['progress']["annotation_ids"] = doc['progress']["annotation_ids"] + annotation_ids
        doc['progress']['upload_ids'] = doc['progress']["upload_ids"] + upload_ids
        doc['progress']['verification_ids'] = doc['progress']['verification_ids'] + verification_ids

        if doc['status'] == MissionStatus.READY_TO_START and (
                len(annotation_ids) > 0 or len(upload_ids) > 0 or len(verification_ids) > 0):
            doc['status'] = MissionStatus.IN_PROGRESS

        target = doc['criteria']['target']
        if doc['type'] == MissionType.UPLOAD and len(doc['progress']['upload_ids']) >= target:
            doc['status'] = MissionStatus.COMPLETED
            doc['reward_status'] = MissionRewardStatus.ready_to_pay
        elif doc['type'] == MissionType.ANNOTATE and len(doc['progress']['annotation_ids']) >= target:
            doc['status'] = MissionStatus.COMPLETED
            doc['reward_status'] = MissionRewardStatus.ready_to_pay
        elif doc['type'] == MissionType.VERIFY and len(doc['progress']['verification_ids']) >= target:
            doc['status'] = MissionStatus.COMPLETED
            doc['reward_status'] = MissionRewardStatus.ready_to_pay

        self.update_doc(mission_id, doc)


missions_dao = MissionsDao()
missions_dao.set_config(
    config["couchdb"]["user"],
    config["couchdb"]["password"],
    config["couchdb"]["db_host"],
    config["couchdb"]["missions_db"],
)
