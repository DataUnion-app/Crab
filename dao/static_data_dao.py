from dao.base_dao import BaseDao
from datetime import datetime
from utils.get_random_string import get_random_string


class StaticDataDao(BaseDao):

    def add_banned_words(self, words):
        selector = {
            "selector": {
                "_id": {
                    "$gt": None
                },
                "type": "banned_words",
            },
            "limit": 1,
            "skip": 0,
        }

        documents = self.query_data(selector)['result']

        if len(documents) == 0:
            doc_id = get_random_string(10)
            self.save(doc_id, {
                "version": 1,
                "type": "banned_words",
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

    def get_banned_words(self):
        selector = {
            "selector": {
                "_id": {
                    "$gt": None
                },
                "type": "banned_words",
            },
            "limit": 1,
            "skip": 0,
        }

        documents = self.query_data(selector)['result']

        if len(documents) == 0:
            return []
        else:
            return documents[0]['words']
