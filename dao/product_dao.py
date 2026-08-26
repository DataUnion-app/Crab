import datetime

from dao.base_dao import BaseDao
from config import config
from utils.get_random_string import get_random_string
from models.metadata.metadata_models import Source

class ProductDao(BaseDao):
    def __init__(self):
        super(ProductDao, self).__init__()
        self.id_prefix = "product"

    def create_product(self, public_address: str, name: str, material_type: str, material_size: str, example_image: str, source: Source = Source.default) -> str:
        doc_id = product_dao.generate_new_doc_id()
        document = dict()
        document['public_address'] = public_address
        document['name'] = name
        document['material_type'] = material_type
        document['material_size'] = material_size
        document['example_image'] = example_image
        document['created_at'] = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f%Z")
        document['source'] = source
        self.save(doc_id, document)
        return doc_id

    def get_product_by_id(self, doc_id: str) -> dict:
        return self.get_doc_by_id(doc_id)

    def get_products_by_public_address(self, public_address):
        selector = {
            "selector": {"_id": {"$gt": None}, "public_address": public_address}
        }
        return self.query_data(selector)
    
    def get_all_products(self):
        selector = {
            "selector": {"_id": {"$gt": None}}
        }
        return self.query_data(selector)

product_dao = ProductDao()
product_dao.set_config(
    config["couchdb"]["user"],
    config["couchdb"]["password"],
    config["couchdb"]["db_host"],
    config["couchdb"]["product_db"],
)
