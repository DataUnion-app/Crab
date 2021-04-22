from config import config
from dao.base_dao import BaseDao
from datetime import datetime
from utils.get_random_string import get_random_string


class SessionsDao(BaseDao):

    def add_to_blacklist(self, jti):
        doc_id = get_random_string()
        self.save(doc_id, {'jti': jti, 'black_listed': True, 'created_at': datetime.timestamp(datetime.now())})

    def is_blacklisted(self, jti):
        selector = {"selector": {"_id": {"$gt": None}, "jti": jti}}
        result = self.query_data(selector)["result"]
        if len(result) == 1:
            return True
        return False


sessions_dao = SessionsDao()
sessions_dao.set_config(config['couchdb']['user'], config['couchdb']['password'], config['couchdb']['db_host'],
                    config['couchdb']['sessions_db'])
