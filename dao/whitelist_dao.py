from dao.base_dao import BaseDao
from utils.get_random_string import get_random_string


class WhitelistDao(BaseDao):
    def save_whitelists(self, white_lists=[]):
        documents = self.get_all()["result"]
        data = {}

        if not documents:
            doc_id = get_random_string()
        else:
            doc_id = documents[0]["_id"]
            data = documents[0]
        data["whitelist"] = white_lists
        result = self.save(doc_id, data)
        return result

    def get_whitelists(self):
        documents = self.get_all()["result"]

        if not documents:
            return []
        return documents[0]["whitelist"]
