import datetime

from dao.base_dao import BaseDao
from config import config
from models.metadata.metadata_models import Source

class DeviceDao(BaseDao):
    def __init__(self):
        super(DeviceDao, self).__init__()
        self.id_prefix = "device"

    def create_device_with_device_id(self, device_id: str, source: Source = Source.default) -> str:
        doc_id = device_dao.generate_new_doc_id()
        document = dict()
        document['device_id'] = device_id
        document['created_at'] = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f%Z")
        document['source'] = source
        self.save(doc_id, document)
        return doc_id

    def create_device(self, document: dict, source: Source = Source.default) -> str:
        doc_id = device_dao.generate_new_doc_id()
        document['created_at'] = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f%Z")
        document['source'] = source
        self.save(doc_id, document)
        return doc_id

    def get_device_by_id(self, doc_id: str) -> dict:
        return self.get_doc_by_id(doc_id)

    def get_device_by_device_id(self, device_id: str) -> dict:
        selector = {
            "selector": {"_id": {"$gt": None}, "device_id": device_id}
        }
        return self.query_data(selector)

    def get_devices_by_public_address(self, public_address):
        selector = {
            "selector": {"_id": {"$gt": None}, "public_address": public_address}
        }
        return self.query_data(selector)
    
    def get_all_devices(self):
        selector = {
            "selector": {"_id": {"$gt": None}}
        }
        return self.query_data(selector)

    def set_public_address(self, doc_id: str, public_address: str):
        device = self.get_device_by_id(doc_id)
        device['public_address'] = public_address
        self.update_doc(doc_id, device)
        return True

device_dao = DeviceDao()
device_dao.set_config(
    config["couchdb"]["user"],
    config["couchdb"]["password"],
    config["couchdb"]["db_host"],
    config["couchdb"]["device_db"],
)
