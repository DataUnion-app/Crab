from config import config
from dao.base_dao import BaseDao
from datetime import datetime
from utils.get_random_string import get_random_string


class ChallengesDao(BaseDao):

    def add_new_challenge(self, challenge_name, status, description, rules):
        doc_id = get_random_string()
        result = self.save(doc_id,
                           {
                               'name': challenge_name,
                               'status': status,
                               'description': description,
                               'start_date': datetime.timestamp(datetime.now()),
                               'end_date': datetime.timestamp(datetime.now()),
                               'rules': rules
                           }
                           )
        return result


challenges_dao = ChallengesDao()
challenges_dao.set_config(config['couchdb']['user'], config['couchdb']['password'], config['couchdb']['db_host'],
                          config['couchdb']['challenges_dao'])
