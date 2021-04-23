from config import config
from dao.base_dao import BaseDao
from datetime import datetime
from utils.get_random_string import get_random_string
from enum import Enum


class WordTypes(Enum):
    BANNED_WORDS = 1,
    RECOMMENDED_WORDS = 2


class StaticDataDao(BaseDao):

    def add_words(self, words, type):
        selector = {
            "selector": {
                "_id": {
                    "$gt": None
                },
                "type": type,
            },
            "limit": 1,
            "skip": 0,
        }

        documents = self.query_data(selector)['result']

        if len(documents) == 0:
            doc_id = get_random_string(10)
            self.save(doc_id, {
                "version": 1,
                "type": type,
                "words": words,
                "created_at": datetime.timestamp(datetime.now()),
                "updated_at": datetime.timestamp(datetime.now())
            })
        else:
            document = documents[0]
            document['updated_at'] = datetime.timestamp(datetime.now())
            document['words'] = list(set(document['words']).union(words))
            document['version'] = document['version'] + 1
            self.update_doc(document['_id'], document)

    def get_words_by_type(self, type):
        selector = {
            "selector": {
                "_id": {
                    "$gt": None
                },
                "type": type,
            },
            "limit": 1,
            "skip": 0,
        }

        documents = self.query_data(selector)['result']

        if len(documents) == 0:
            return []
        else:
            return documents[0]['words']


static_data_dao = StaticDataDao()
static_data_dao.set_config(config['couchdb']['user'], config['couchdb']['password'], config['couchdb']['db_host'],
                    config['couchdb']['users_db'])
