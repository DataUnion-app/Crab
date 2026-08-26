import datetime

from dao.base_dao import BaseDao
from config import config
from utils.get_random_string import get_random_string

class IncidentDao(BaseDao):
    def __init__(self):
        super().__init__()

    def create_incident(self, user_id: str, description: str) -> str:
        doc_id = get_random_string(15)
        document = dict()
        document['user_id'] = user_id
        document['description'] = description
        document['created_at'] = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f%Z")
        return self.save(doc_id, document)['id']

    def get_incident(self, doc_id: str) -> dict:
        return self.get_doc_by_id(doc_id)

    def get_by_user_id(self, user_id):
        selector = {
            "selector": {"_id": {"$gt": None}, "user_id": user_id}
        }
        return self.query_data(selector)
    
    def get_all_incidents(self):
        selector = {
            "selector": {"_id": {"$gt": None}}
        }
        return self.query_data(selector)

incident_dao = IncidentDao()
incident_dao.set_config(
    config["couchdb"]["user"],
    config["couchdb"]["password"],
    config["couchdb"]["db_host"],
    config["couchdb"]["incident_db"],
)
