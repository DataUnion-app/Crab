from config import config
from dao.base_dao import BaseDao, DBResultError
from datetime import datetime
from utils.get_random_string import get_random_string
from enum import Enum


class WordTypes(str, Enum):
    BANNED_WORDS = 'BANNED_WORDS'
    RECOMMENDED_WORDS = 'RECOMMENDED_WORDS'


class StaticDataDao(BaseDao):
    def add_words(self, words, type):
        selector = {
            "selector": {
                "_id": {"$gt": None},
                "type": type,
            },
            "limit": 1,
            "skip": 0,
        }

        documents = self.query_data(selector)["result"]

        if len(documents) == 0:
            doc_id = get_random_string(10)
            self.save(
                doc_id,
                {
                    "version": 1,
                    "type": type,
                    "words": words,
                    "created_at": datetime.timestamp(datetime.now()),
                    "updated_at": datetime.timestamp(datetime.now()),
                },
            )
        else:
            document = documents[0]
            document["updated_at"] = datetime.timestamp(datetime.now())
            document["words"] = list(set(document["words"]).union(words))
            document["version"] = document["version"] + 1
            self.update_doc(document["_id"], document)

    def get_words_by_type(self, type):
        selector = {
            "selector": {
                "_id": {"$gt": None},
                "type": type,
            },
            "limit": 1,
            "skip": 0,
        }

        documents = self.query_data(selector)["result"]

        if len(documents) == 0:
            return []
        else:
            return documents[0]["words"]

    def create_route_permission_doc(self, enable_annotations, enable_uploads):
        doc_id = "routes_permission_configuration"
        already_exists = self.exists(doc_id)

        if not already_exists:
            self.save(
                doc_id,
                {
                    "annotations": enable_annotations,
                    "uploads": enable_uploads,
                    "created_at": datetime.utcnow().timestamp(),
                    "updated_at": datetime.utcnow().timestamp(),
                },
            )

    def get_route_permission_doc(self):
        document = self.get_doc_by_id("routes_permission_configuration")

        if not document:
            raise DBResultError(self.db_name,
                                "route permission document doesn't exist in the database")
        return document


static_data_dao = StaticDataDao()
static_data_dao.set_config(
    config["couchdb"]["user"],
    config["couchdb"]["password"],
    config["couchdb"]["db_host"],
    config["couchdb"]["static_data_db"],
)
