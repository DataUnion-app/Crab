import datetime

from dao.base_dao import BaseDao
from config import config
from utils.get_random_string import get_random_string
from models.metadata.metadata_models import Source, QRCodeStatus, EntityRewardStatus, QRCodeType

class QRCodeDao(BaseDao):
    def __init__(self):
        super().__init__()

    def create_qrcode(self, created_by: str, product_id: str, 
        batch_id: str, qr_code: str, hash_value: str, filepath: str, source: Source = Source.default) -> str:
        doc_id = get_random_string(15)
        document = dict({})
        document['created_by'] = created_by
        document['product_id'] = product_id
        document['batch_id'] = batch_id
        document['status'] = QRCodeStatus.created
        document['created_at'] = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f%Z")
        document['source'] = source
        document["qr_code"] = qr_code
        document["hash"] = hash_value
        document["filepath"] = filepath
        return self.save(doc_id, document)['id']

    def create_new_qrcode(
        self, 
        created_by: str, 
        product_id: str, 
        batch_id: str, 
        qr_code: str, 
        hash_value: str,
        status: str,
        aggregated_status: bool,
        type: str,
        filepath: str, 
        source: Source = Source.default
    ) -> str:
        doc_id = get_random_string(15)
        document = dict({})
        document['created_by'] = created_by
        document['product_id'] = product_id
        document['batch_id'] = batch_id
        document['qr_code'] = qr_code
        document['hash'] = hash_value
        document['status'] = QRCodeStatus.created
        document['aggregated_status'] = aggregated_status
        document['type'] = type
        document["filepath"] = filepath
        document['source'] = source
        document['created_at'] = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f%Z")
        return self.save(doc_id, document)['id']

    def is_exist_qrcode(self, qr_codes:list, bounty_id):
        selector = {"selector": {"_id": {"$gt": None}, "qr_code": qr_codes, "bounty_id": bounty_id}}
        result = self.query_data(selector)["result"]
        if len(result) > 0:
            return True
        return False

    def is_exist(self, qr_codes:list):
        selector = {"selector": {"_id": {"$gt": None}, "qr_code": qr_codes}}
        result = self.query_data(selector)["result"]
        if len(result) > 0:
            return True
        return False
    
    def is_exist_qrcode_bounty_id_status(self, qr_codes:list, bounty_id, status: QRCodeStatus):
        selector = {"selector": {"_id": {"$gt": None}, "qr_code": qr_codes, "bounty_id": bounty_id, "status": status}}
        result = self.query_data(selector)["result"]
        if len(result) > 0:
            return True
        return False
    
    def get_qrcode_by_id(self, doc_id: str) -> dict:
        return self.get_doc_by_id(doc_id)

    def get_qrcode_by_qr_code(self, qr_code: str) -> dict:
        selector = {"selector": {"$or": [{"qr_code": qr_code}, {"hash": qr_code}]}}
        qrcodes = self.query_data(selector)['result']
        if len(qrcodes) > 0:
            return qrcodes[0]
        else:
            return None

    def get_scanned_qrcodes_by_collector(self, public_address: str, product_id: str = None, batch_ids: list = []):
        selector = {
            "selector": {"_id": {"$gt": None}, "scanned_by": public_address, "status": QRCodeStatus.scanned}
        }
        if product_id is not None:
            selector["selector"]["product_id"] = product_id
        if len(batch_ids) > 0:
            selector["selector"]["batch_id"] = {"$in": batch_ids}

        return self.query_data(selector)['result']

    def get_qrcodes_by_public_address(self, public_address):
        selector = {
            "selector": {"_id": {"$gt": None}, "public_address": public_address}
        }
        return self.query_data(selector)

    def get_qrcodes_by_batch_id_and_type(self, batch_id, type):
        selector = {
            "selector": {"_id": {"$gt": None}, "batch_id": batch_id, "type": type}
        }
        return self.query_data(selector)["result"]
    
    def get_qrcodes_by_public_address_bounty_id(self, public_address, bounty_id):
        selector = {
            "selector": {"_id": {"$gt": None}, 
            "public_address": public_address,
            "bounty_id": bounty_id},
            'fields': ["_id","qr_code","filepath", "status"]
        }
        return self.query_data(selector)["result"]
    
    def get_qrcodes_by_bounty_id_status(self, bounty_id, status: QRCodeStatus):
        selector = {
            "selector": {"_id": {"$gt": None}, "bounty_id": bounty_id, "status": status},
            'fields': ["public_address", "qr_code", "status", "updated_at"],
        }
        return self.query_data(selector)["result"]
    
    def get_qrcodes_by_public_address_status(self, public_address, status: QRCodeStatus):
        selector = {
            "selector": {"_id": {"$gt": None}, "public_address": public_address, "status": status},
            'fields': ["public_address", "qr_code", "status"],
        }
        return self.query_data(selector)["result"]
    
    def get_qrcodes_by_bounty_id(self, bounty_id):
        selector = {
            "selector": {"_id": {"$gt": None}, "bounty_id": bounty_id}
        }
        return self.query_data(selector)

    def get_qrcodes_by_batch_id(self, batch_id):
        selector = {
            "selector": {"_id": {"$gt": None}, "batch_id": batch_id}
        }
        return self.query_data(selector)

    def get_qrcodes_by_qrcode(self, qrcode: str):
        selector = {
            "selector": {"_id": {"$gt": None}, "qr_code": qrcode}
        }
        return self.query_data(selector)["result"]
    
    def get_reward_by_qrcode_bounty_id(self, qrcode: list, bounty_id: str):
        selector = {
            "selector": {"_id": {"$gt": None}, "qr_code": qrcode, "bounty_id": bounty_id}
        }
        documents = self.query_data(selector)["result"]
        if len(documents) != 1:
            return None
        
        if documents[0].get("reward") == None:
            return None
        else:
            return documents[0].get("reward")
    
    def get_qrcodes_by_bounty_id(self, bounty_id):
        selector = {
            "selector": {"_id": {"$gt": None}, "bounty_id": bounty_id}
        }
        return self.query_data(selector)
    
    def get_qrcodes_by_product_id(self, product_id):
        selector = {
            "selector": {"_id": {"$gt": None}, "product_id": product_id}
        }
        return self.query_data(selector)

    def get_qrcodes_by_bounty_id_start_end_date(self, bounty_id, product_id, batch_name, start_date, end_date):
        selector = {
            "selector": {"_id": {"$gt": None}
            }
        }
        if bounty_id is not None:
            selector["selector"]["bounty_id"] = bounty_id
        if product_id is not None:
            selector["selector"]["product_id"] = product_id
        if batch_name is not None:
            selector["selector"]["batch_name"] = batch_name
        if start_date is not None and end_date is not None:
            selector["selector"]["updated_at"] = {"$gte": start_date,"$lt": end_date}
        return self.query_data(selector)
    
    def get_all_qrcodes(self):
        selector = {
            "selector": {"_id": {"$gt": None}}
        }
        return self.query_data(selector)
    
    def update_status(self, public_address, qrcode, bounty_id, status: QRCodeStatus):
        selector = {"selector": {"_id": {"$gt": None}, "qr_code": qrcode, "bounty_id": bounty_id}}
        result = self.query_data(selector)["result"]
        if len(result) > 0:
            doc_id = result[0]["_id"]
            doc = self.get_doc_by_id(doc_id)
            doc["updated_at"] = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f%Z")
            doc['status'] = status
            doc['uploaded_by'] = public_address
            return self.update_doc(doc_id, doc)
        return False
    
    def set_status_by_qrcode(self, public_address: str, qrcode: list, status: QRCodeStatus):
        doc_id = self.get_qrcodes_by_qrcode(qrcode)[0]["_id"]
        doc = self.get_doc_by_id(doc_id)
        doc['status'] = status
        doc['updated_at'] = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f%Z")
        doc['uploaded_by'] = public_address
        self.update_doc(doc_id, doc)
        return doc

    def set_status_by_qrcode_recycler(self, public_address: str, qrcode: list, status: QRCodeStatus):
        doc_id = self.get_qrcodes_by_qrcode(qrcode)[0]["_id"]
        doc = self.get_doc_by_id(doc_id)
        doc['status'] = status
        doc['updated_at'] = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f%Z")
        doc['recycled_by'] = public_address
        self.update_doc(doc_id, doc)
        return doc

    def set_status(self, public_address, doc_id, status: QRCodeStatus):
        doc = self.get_doc_by_id(doc_id)
        doc['status'] = status
        doc['updated_at'] = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f%Z")
        doc['uploaded_by'] = public_address
        self.update_doc(doc_id, doc)
        return doc

    def set_status(self, doc_id, status: QRCodeStatus):
        doc = self.get_doc_by_id(doc_id)
        doc['status'] = status
        self.update_doc(doc_id, doc)
        return doc
    
    def set_transfer_status_by_qrcode(self, public_address: str, qrcode: list, bounty_id: str, reward_status: EntityRewardStatus):
        selector = {"selector": {"_id": {"$gt": None}, "qr_code": qrcode, "bounty_id": bounty_id}}
        result = self.query_data(selector)["result"]
        if len(result) > 0:
            doc_id = result[0]["_id"]
            doc = self.get_doc_by_id(doc_id)
            doc["updated_at"] = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f%Z")
            doc['reward_status'] = reward_status
            doc['uploaded_by'] = public_address
            return self.update_doc(doc_id, doc)
        return False

qrcode_dao = QRCodeDao()
qrcode_dao.set_config(
    config["couchdb"]["user"],
    config["couchdb"]["password"],
    config["couchdb"]["db_host"],
    config["couchdb"]["qrcode_db"],
)
