import requests
from .BaseDao import BaseDao
import json
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
