import datetime
from typing import List

from dao.base_dao import BaseDao
from config import config
from models.User import UserRoleType
from models.bounty import BountyStatus, BountyType


class BountyDao(BaseDao):
    def __init__(self):
        super(BountyDao).__init__()
        self.id_prefix = 'bounty'
        self.page_size = 100

    def search_bounty(self, status: BountyStatus, bounty_type: BountyType, page: int = 1):
        query = {"selector": {"status": status, "bounty_type": bounty_type},
                 'skip': self.page_size * (page - 1),
                 'sort': [{'missions_count': 'asc'}],
                 'limit': self.page_size}
        result = self.query_data(query)["result"]
        return result

    def get_bounties_by_user(self, public_address: str, roles: List[UserRoleType]):
        query = {"selector": {"created_by": public_address}}
        result = self.query_all(query)
        return result

    def get_bounties_by_public_address(self, created_by: str):
        query = {"selector": {"created_by": created_by}}
        result = self.query_all(query)
        return result

    def get_bounties_by_entity_list_id(self, entity_list_id: str):
        query = {"selector": {"entity_list_id": entity_list_id}}
        result = self.query_all(query)
        return result

    # def update_progress(self, bounty_id: str, image_uploads: List[str] = ()):
    #     document = self.get_doc_by_id(bounty_id)
    #     if document.get('progress') is None:
    #         document['progress'] = []
    #     document['updated_at'] = datetime.datetime.utcnow().isoformat()
    #     document['progress'] = document['progress'] + image_uploads
    #     self.update_doc(bounty_id, document)
    def update_bounty(self, bounty_id, state):
        selector = {
            "selector": {"_id": {"$gt": None}, "_id": bounty_id}
        }
        data = self.query_data(selector)
        data["result"][0]["status"] = state
        self.save(bounty_id, data["result"][0])
        return state

    def search_by_status_pagination(self, status, page_size: int = 10, page: int = 1):
        selector = {
            "selector": {"_id": {"$gt": None}, "status": status},
            'fields': ["_id", "status", "created_at", "bounty_name", "bounty_description", "company_name", "company_description"],
            'skip': page_size * page,
            'limit': page_size}
        return self.query_data(selector)
    
    def search_by_status_pagination_all_fields(self, status, page_size: int = 10, page: int = 1):
        selector = {
            "selector": {"_id": {"$gt": None}, "status": status},
            'skip': page_size * page,
            'limit': page_size}
        return self.query_data(selector)

    def get_bounties_by_batch_id(self, batch_id):
        selector = {
            "selector": {"_id": {"$gt": None}, "batch_ids": {"$elemMatch": {"$eq": batch_id}}},
        }
        return self.query_data(selector)["result"]

bounty_dao = BountyDao()
bounty_dao.set_config(
    config["couchdb"]["user"],
    config["couchdb"]["password"],
    config["couchdb"]["db_host"],
    config["couchdb"]["bounty_db"],
)
