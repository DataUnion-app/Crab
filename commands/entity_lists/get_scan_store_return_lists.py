from commands.base_command import BaseCommand
from dao.users_dao import user_dao
from dao.incident_dao import incident_dao
from dao.rewards_dao import rewards_dao
from dao.entity_list_dao import entity_list_dao
from dao.bounty_dao import bounty_dao
from commands.stats.success_rate import SuccessRate

class GetScanStoredScannedListsCommand(BaseCommand):

    def __init__(self, public_address: str):
        super(GetScanStoredScannedListsCommand, self).__init__()
        self.public_address = public_address

    def execute(self):
        doc = {}
        scanned_list = entity_list_dao.get_scanned_entity_lists_by_public_address(self.public_address)
        if len(scanned_list) > 0:
            scanned_list[0]["type"] = "Scanned"
            entity_list_id = scanned_list[0]["_id"]
            bounties = bounty_dao.get_bounties_by_entity_list_id(entity_list_id)
            if len(bounties) > 0:
                scanned_list[0]["log_name"] = bounties[0]["bounty_name"]
                scanned_list[0]["company_name"] = bounties[0]["company_name"]
                scanned_list[0]["profile_image"] = bounties[0]["_attachments"]
                scanned_list[0]["number_of_scans"] = len(scanned_list[0]["entity_ids"])

        stored_list = entity_list_dao.get_stored_entity_lists_by_public_address(self.public_address)
        if len(stored_list) > 0:
            stored_list[0]["type"] = "Stored"
            entity_list_id = stored_list[0]["_id"]
            bounties = bounty_dao.get_bounties_by_entity_list_id(entity_list_id)
            if len(bounties) > 0:
                stored_list[0]["log_name"] = bounties[0]["bounty_name"]
                stored_list[0]["company_name"] = bounties[0]["company_name"]
                stored_list[0]["profile_image"] = bounties[0]["_attachments"]
                stored_list[0]["number_of_scans"] = len(scanned_list[0]["entity_ids"])

        returned_list = entity_list_dao.get_returned_entity_lists_by_public_address(self.public_address)
        if len(returned_list) > 0:
            returned_list[0]["type"] = "Returned"
            entity_list_id = returned_list[0]["_id"]
            bounties = bounty_dao.get_bounties_by_entity_list_id(entity_list_id)
            if len(bounties) > 0:
                returned_list[0]["log_name"] = bounties[0]["bounty_name"]
                returned_list[0]["company_name"] = bounties[0]["company_name"]
                returned_list[0]["profile_image"] = bounties[0]["_attachments"]
                returned_list[0]["number_of_scans"] = len(scanned_list[0]["entity_ids"])
        doc["scanned_list"] = scanned_list
        doc["stored_list"] = stored_list
        doc["returned_list"] = returned_list
        self.successful = True
        return doc