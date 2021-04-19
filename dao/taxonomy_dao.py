from dao.base_dao import BaseDao
from config import config


class TaxonomyDao(BaseDao):
    def __init__(self):
        super().__init__()

    def get_verifiable_images(self, public_address):
        selector = {
            "selector": {
                "status": "VERIFIABLE",
                "$not": {
                    "verified": {
                        "$elemMatch": {
                            "by": {
                                "$eq": public_address
                            }
                        }
                    }
                }

            },
            "sort": [
                {
                    "created_at": "desc"
                }
            ],
            "fields": [
                "_id"
            ],
            "limit": self.page_size,
            "skip": 0
        }

        result = self.query_data(selector)['result']
        res = [{'image_id': r['_id']} for r in result]
        return res


taxonomy_dao = TaxonomyDao()
taxonomy_dao.set_config(config['couchdb']['user'], config['couchdb']['password'], config['couchdb']['db_host'],
                        config['couchdb']['taxonomy_db'])
