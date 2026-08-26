from datetime import datetime
from typing import List

from config import config
from dao.base_dao import BaseDao
from models.entity_list_models import EntityListType
from models.metadata.metadata_models import EntityType, Source
from utils.get_random_string import get_random_string


class EntityListDao(BaseDao):
    def __init__(self):
        super(EntityListDao, self).__init__()
        self.id_prefix = "entity_list"

    def update_list(self, doc_id: str, data: list, entity_list_type: EntityListType, name: str,
                    description: str = None, image: str = None):
        document = self.get_doc_by_id(doc_id)
        document['updated_at'] = datetime.now().replace(microsecond=0).isoformat()
        document["entity_ids"] = data
        document["entity_list_type"] = entity_list_type
        document["description"] = description
        document["name"] = name if name else document["name"]
        document["image"] = image if image else document["image"]

        self.update_doc(doc_id, document)

    def create_list(self,
                    public_address: str,
                    entity_type: EntityType,
                    entity_ids,
                    entity_list_type: EntityListType,
                    name: str,
                    description: str = None,
                    favourites_of: list = [], image: str = None, source: Source = Source.default) -> str:
        doc_id = entity_list_dao.generate_new_doc_id()
        created_time = datetime.now().replace(microsecond=0).isoformat()

        document = {
            'updated_at': created_time,
            'created_at': created_time,
            'entity_type': entity_type,
            'entity_list_type': entity_list_type,
            'public_address': public_address,
            'entity_ids': entity_ids,
            'description': description,
            'name': name,
            'favorites_of': favourites_of,
            'image': image
        }

        if source == Source.recyclium:
            document['qr_code'] = get_random_string(15)

        self.save(doc_id, document)
        return doc_id

    def create_new_list(self,
                    created_by: str,
                    entity_type: EntityType,
                    entity_ids,
                    entity_list_type: EntityListType,
                    filepath: str,
                    qr_code: str,
                    source: Source = Source.default) -> str:
        doc_id = entity_list_dao.generate_new_doc_id()
        created_time = datetime.now().replace(microsecond=0).isoformat()

        document = {
            'updated_at': created_time,
            'created_at': created_time,
            'entity_type': entity_type,
            'entity_list_type': entity_list_type,
            'created_by': created_by,
            'entity_ids': entity_ids,
            'filepath': filepath,
            'qr_code': qr_code,
            'source': source
        }

        self.save(doc_id, document)
        return doc_id

    def get_user_lists(self, public_address: str, entity_type: EntityType, page: int = 1):
        query = {
            'selector': {
                'public_address': public_address,
                'entity_type': entity_type
            },
            'skip': self.page_size * (page - 1),
            'sort': [{'updated_at': 'asc'}],
            'limit': self.page_size
        }
        return self.query_data(query)["result"]

    def get_entity_lists_by_public_address(self, public_address: str):
        query = {
            'selector': {
                'public_address': public_address
            }
        }  
        return self.query_data(query)["result"]

    def get_scanned_entity_lists_by_public_address(self, public_address: str):
        query = {
            'selector': {
                'public_address': public_address,
                'entity_ids':{"$exists": True },
            }
        }
        return self.query_data(query)["result"]

    def get_stored_entity_lists_by_public_address(self, public_address: str):
        query = {
            'selector': {
                'public_address': public_address,
                'accepted_image_ids':{"$exists": True }
            }
        }
        return self.query_data(query)["result"]

    def get_returned_entity_lists_by_public_address(self, public_address: str):
        query = {
            'selector': {
                'public_address': public_address,
                'rejected_image_ids':{"$exists": True }
            }
        }
        return self.query_data(query)["result"]
    
    def delete_list(self, doc_id: str):
        self.delete_doc(doc_id)

    def get_all_public_lists(self, entity_type: EntityType, entity_list_id: str, page: int = 1):
        query = {
            'selector': {
                'entity_list_type': EntityListType.PUBLIC,
                'entity_type': entity_type
            },
            'skip': self.page_size * (page - 1),
            'sort': [{'updated_at': 'asc'}],
            'limit': self.page_size
        }

        if entity_list_id:
            query['selector']['_id'] = entity_list_id

        return self.query_data(query)["result"]

    def get_favorite_entities(self, public_address: str):
        query = {
            "selector": {
                "favorites_of": {
                    "$elemMatch": {
                        "$eq": public_address
                    }
                }
            }
        }
        return self.query_data(query)["result"]

    def update_bounty_progress(self, entity_list_id: str, entity_ids: List[str]):
        document = self.get_doc_by_id(entity_list_id)
        document['entity_ids'] = document['entity_ids'] + entity_ids
        document['updated_at'] = datetime.utcnow().isoformat()
        return self.update_doc(entity_list_id, document)

    # TODO: Optimize db query. Create a view that returns count.
    def get_entity_list_length(self, entity_list_id: str):
        document = self.get_doc_by_id(entity_list_id)
        return len(document['entity_ids'])

    def get_entity_lists_by_entity_id_scanned(self, entity_id):
        selector = {
            'selector': {
            "_id": {"$gt": None},
            'entity_ids': {'$elemMatch': {'$eq': entity_id}}
            }
        }
        return self.query_data(selector)['result']

    def get_entity_lists_by_entity_id_from_accepted(self, entity_id):
        selector = {
            'selector': {
            "_id": {"$gt": None},
            'accepted_image_ids': {'$elemMatch': {'$eq': entity_id}}
            }
        }
        return self.query_data(selector)['result']

    def get_entity_lists_by_entity_id_from_rejected(self, entity_id):
        selector = {
            'selector': {
            "_id": {"$gt": None},
            'rejected_image_ids': {'$elemMatch': {'$eq': entity_id}}
            }
        }
        return self.query_data(selector)['result']

    def get_entity_lists_by_entity_id(self, entity_id):
        selector = {
            'selector': {
                '_id': {'$gt': None},
                '$or': [
                    {'entity_ids': {'$elemMatch': {'$eq': entity_id}}},
                    {'accepted_image_ids': {'$elemMatch': {'$eq': entity_id}}},
                    {'rejected_image_ids': {'$elemMatch': {'$eq': entity_id}}}
                ]
            }
        }
        return self.query_data(selector)['result']

    def add_entities_to_list(self, doc_id: str, entity_ids: List[str]):
        document = self.get_doc_by_id(doc_id)
        document['updated_at'] = datetime.now().replace(microsecond=0).isoformat()
        document["entity_ids"] = list(set(document["entity_ids"] + entity_ids))
        self.update_doc(doc_id, document)


entity_list_dao = EntityListDao()
entity_list_dao.set_config(
    config["couchdb"]["user"],
    config["couchdb"]["password"],
    config["couchdb"]["db_host"],
    config["couchdb"]["entity_list_db"],
)
