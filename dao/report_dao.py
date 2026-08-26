import datetime

from dao.base_dao import BaseDao
from config import config
from utils.get_random_string import get_random_string
from models.metadata.metadata_models import Source

class ReportDao(BaseDao):
    def __init__(self):
        super().__init__()

    def create_report(self, public_address: str, filename: str, filepath: str, filesize: str, filetype: str, mission_id: str,  source: Source = Source.default) -> str:
        doc_id = get_random_string(15)
        document = dict({})
        document['public_address'] = public_address
        document['filename'] = filename
        document['filepath'] = filepath
        document['filesize'] = filesize
        document['filetype'] = filetype
        document['mission_id'] = mission_id
        document['created_at'] = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f%Z")
        document['source'] = source
        return self.save(doc_id, document)['id']

    def get_report_by_id(self, doc_id: str) -> dict:
        return self.get_doc_by_id(doc_id)

    def get_reports_by_public_address(self, public_address, filetype):
        selector = {
            "selector": {"_id": {"$gt": None}, "public_address": public_address, "filetype": filetype}
        }
        return self.query_data(selector)
    
    def get_reports_by_filter(self, public_address, sort_by, mission_id, start_date, end_date):
        selector = {
            "selector": {"_id": {"$gt": None}, "public_address": public_address},
            "sort": [{"created_at": sort_by}]
        }
        if mission_id is not None:
            selector["selector"]["mission_id"] = mission_id
        if start_date is not None and end_date is not None:
            selector["selector"]["created_at"] = {"$gte": start_date,"$lt": end_date}
        print(selector)
        return self.query_data(selector)
    
    def get_all_reports(self):
        selector = {
            "selector": {"_id": {"$gt": None}}
        }
        return self.query_data(selector)

report_dao = ReportDao()
report_dao.set_config(
    config["couchdb"]["user"],
    config["couchdb"]["password"],
    config["couchdb"]["db_host"],
    config["couchdb"]["report_db"],
)
