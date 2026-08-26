from config import config
from dao.base_dao import BaseDao
from datetime import datetime
from utils.get_random_string import get_random_string


class ChallengesDao(BaseDao):
    def add_new_challenge(self, challenge_name, status, description, rules):
        doc_id = get_random_string()
        result = self.save(
            doc_id,
            {
                "name": challenge_name,
                "status": status,
                "description": description,
                "start_date": datetime.timestamp(datetime.now()),
                "end_date": datetime.timestamp(datetime.now()),
                "rules": rules,
            },
        )
        return result

    def get_all_challenge(self):
        selector = {"selector": {"_id": {"$gt": None}}}

        result = self.query_data(selector)["result"]
        res = [
            {
                "challenge_id": r["_id"],
                "name": r["name"],
                "description": r["description"],
                "status": r["status"],
                "rules": r["rules"],
                "start_date": r["start_date"],
                "end_date": r["end_date"],
            }
            for r in result
        ]
        return res

    def update_challenge(
        self,
        challenge_id: str,
        challenge_name: str,
        status: str,
        description: str,
        rules: str,
    ):
        document = self.get_doc_by_id(challenge_id)
        document["name"] = challenge_name
        document["status"] = status
        document["description"] = description
        document["rules"] = rules
        document["end_date"] = datetime.timestamp(datetime.now())
        result = self.update_doc(challenge_id, document)
        return result


challenges_dao = ChallengesDao()
challenges_dao.set_config(
    config["couchdb"]["user"],
    config["couchdb"]["password"],
    config["couchdb"]["db_host"],
    config["couchdb"]["challenges_db"],
)
