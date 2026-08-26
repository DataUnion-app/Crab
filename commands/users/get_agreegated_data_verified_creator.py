from commands.base_command import BaseCommand
from dao.missions_dao import missions_dao
from dao.users_dao import user_dao
from dao.incident_dao import incident_dao
from dao.rewards_dao import rewards_dao
from commands.stats.success_rate import SuccessRate
from commands.entity_lists.get_scan_store_return_amounts import GetScannedStoredReturnedAmountsCommand
from commands.entity_lists.get_scan_store_return_lists import GetScanStoredScannedListsCommand
from models.metadata.metadata_models import Source

class GetAggregatedDataVerifiedCreatorCommand(BaseCommand):

    def __init__(self, creator_id: str):
        super(GetAggregatedDataVerifiedCreatorCommand, self).__init__()
        self.creator_id = creator_id

    def execute(self):
        user = user_dao.get_doc_by_id(self.creator_id)
        if len(user) == 0:
            self.messages.append("Can't find creator_id")
            self.successful = False
            return
        
        # Get Creator Details
        creator_details = {}
        public_address = user["public_address"]
        creator_details["public_address"] = public_address
        creator_details["profile"] = user.get("profile")
        creator_details["avartar"] = user.get("reserved_avatars")
        
        # Get Log
        logs = {}
        c = GetScanStoredScannedListsCommand(public_address)
        result = c.execute()
        logs["scanned_list"] = result["scanned_list"]
        logs["stored_list"] = result["stored_list"]
        logs["returned_list"] = result["returned_list"]

        # Get Stored and Returned Count
        c = GetScannedStoredReturnedAmountsCommand(public_address)
        result = c.execute()
        creator_details["stored_count"] = result["stored_count"]
        creator_details["returned_count"] = result["returned_count"]

        # Get Missions
        missions = missions_dao.get_missions_by_public_address(public_address)
        if missions:
            creator_details["mission_amount"] = len(missions)

        # Get Incidents
        incidents = incident_dao.get_by_user_id(self.creator_id)["result"]
        if incidents:
            creator_details["incident_amount"] = len(incidents)

        # Get Success Rate
        c = SuccessRate(public_address)
        creator_details["success_rate"] = c.execute()
        
        # Get Total Earned
        creator_details["total_earned"] = rewards_dao.get_total_rewards(public_address)

        #Total Earning Chat
        total_earning_list = rewards_dao.get_total_earning_list(public_address, Source.recyclium)

        doc = {}
        doc["creator_details"] = creator_details
        doc["logs"] = logs
        doc["missions"] = missions
        doc["incidents"] = incidents
        doc["total_earning_chat"] = total_earning_list

        return doc
