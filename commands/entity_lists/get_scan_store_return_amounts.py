from commands.base_command import BaseCommand
from dao.users_dao import user_dao
from dao.incident_dao import incident_dao
from dao.rewards_dao import rewards_dao
from dao.entity_list_dao import entity_list_dao
from commands.stats.success_rate import SuccessRate
from commands.query_view_command import QueryViewCommand, ViewQueryType
from models.db_name import DatabaseName

class GetScannedStoredReturnedAmountsCommand(BaseCommand):

    def __init__(self, public_address: str):
        super(GetScannedStoredReturnedAmountsCommand, self).__init__()
        self.public_address = public_address

    def execute(self):
        entity_lists = entity_list_dao.get_entity_lists_by_public_address(self.public_address)
        doc = {}
        doc["scanned_count"] = 0
        doc["stored_count"] = 0
        doc["returned_count"] = 0
        for data in entity_lists:
            doc_id = data["_id"]
            c = QueryViewCommand(self.public_address, DatabaseName.entity_list, 
                "entity-search-stats", "entity-search-stats", ViewQueryType.user_created_doc_id, doc_id)
            view_result = c.execute()
            if(len(view_result) > 0):
                doc["scanned_count"] += view_result[0]["scanned_count"]
                doc["stored_count"] += view_result[0]["stored_count"]
                doc["returned_count"] += view_result[0]["returned_count"]
        self.successful = True
        return doc