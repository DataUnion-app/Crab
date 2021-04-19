from dao.base_dao import BaseDao
from config import config


class TaxonomyDao(BaseDao):
    def __init__(self):
        super().__init__()


taxonomy_dao = TaxonomyDao()
taxonomy_dao.set_config(config['couchdb']['user'], config['couchdb']['password'], config['couchdb']['db_host'],
                        config['couchdb']['taxonomy_db'])
