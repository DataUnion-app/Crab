import datetime

from dao.base_dao import BaseDao
from config import config
from utils.get_random_string import get_random_string
from models.metadata.metadata_models import Source, CSVStatus

class CSVDao(BaseDao):
    def __init__(self):
        super().__init__()

    def create_csv(self, public_address: str, filename: str, destination_path: str, status: CSVStatus, rows: str, file_size: str, source: Source = Source.default) -> str:
        doc_id = get_random_string(15)
        document = dict({})
        document['public_address'] = public_address
        document["filename"] = filename
        document["uploaded_by"] = public_address
        document["hash"] = doc_id
        document["rows"] = rows
        document["filesize"] = file_size
        document["type"] = "csv"
        document["extension"] = filename.split(".")[-1]
        document["file_path"] = destination_path
        document['status'] = status
        document['created_at'] = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f%Z")
        document['source'] = source
        return self.save(doc_id, document)['id']
    
    def get_csv_by_page(self, page_no: int, per_page: int):
        selector = {
            'sort': [{'created_at': 'desc'}],
            'limit': per_page,
            'skip': per_page * (page_no - 1),
            "selector": {"_id": {"$gt": None}
            }
        }
        return self.query_data(selector)["result"]
    
    def get_csv_by_public_address(self, public_address):
        selector = {
            "selector": {"_id": {"$gt": None}, "public_address": public_address}
        }
        return self.query_data(selector)

    def get_csv_by_user_page(self, public_address: str, page_no: int, per_page: int):
        selector = {
            'sort': [{'created_at': 'desc'}],
            'limit': per_page,
            'skip': per_page * (page_no - 1),
            "selector": {"_id": {"$gt": None}, "public_address" : public_address
            }
        }
        return self.query_data(selector)["result"]

csv_dao = CSVDao()
csv_dao.set_config(
    config["couchdb"]["user"],
    config["couchdb"]["password"],
    config["couchdb"]["db_host"],
    config["couchdb"]["csv_db"],
)