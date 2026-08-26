import logging

from commands.base_command import BaseCommand
from dao.users_dao import user_dao
from dao.rewards_dao import rewards_dao
from dao.entity_list_dao import entity_list_dao
from models.User import UserRoleType

class GetUsersSortbyRewardsClaims(BaseCommand):
    def __init__(self, claims: str):
        super(GetUsersSortbyRewardsClaims, self).__init__()
        self.user_dao = user_dao
        self.claims = claims
        self.rewards_dao = rewards_dao
        self.entity_list_dao = entity_list_dao

    def execute(self):
        users = self.user_dao.get_users_by_claims(self.claims)
        
        for user in users:
            public_address = user.get("public_address")
            rewards = self.rewards_dao.get_total_rewards(public_address)
            user["rewards"] = rewards

            if self.claims == UserRoleType.User:    
                user["collected_amount"] = 0
                scanned_list = entity_list_dao.get_scanned_entity_lists_by_public_address(public_address)
                for collected in scanned_list:
                    user["collected_amount"] = user["collected_amount"] + len(collected.get("entity_ids"))

            elif self.claims == UserRoleType.Storer:    
                user["stored_amount"] = 0
                accepted_list = entity_list_dao.get_stored_entity_lists_by_public_address(public_address)
                for accepted in accepted_list:
                    user["stored_amount"] = user["stored_amount"] + len(accepted.get("accepted_image_ids"))

            elif self.claims == UserRoleType.Creator:    
                user["returned_amount"] = 0
                returned_list = entity_list_dao.get_returned_entity_lists_by_public_address(public_address)
                for returned in returned_list:
                    user["returned_amount"] = user["returned_amount"] + len(returned.get("rejected_image_ids"))
        
        users.sort(key=lambda x: x["rewards"], reverse=True)

        self.successful = True
        return users[:10]

