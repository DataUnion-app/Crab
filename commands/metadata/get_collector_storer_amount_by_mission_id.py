from commands.base_command import BaseCommand
from dao.metadata_dao import image_metadata_dao
from dao.entity_list_dao import entity_list_dao
from dao.users_dao import user_dao
from models.User import UserRoleType

class GetCollectorStorerAmountByMissionID(BaseCommand):
    def __init__(self, mission_id):
        super(GetCollectorStorerAmountByMissionID, self).__init__()
        self.mission_id= mission_id
        self.image_metadata_dao = image_metadata_dao

    def execute(self):
        collectors = self.image_metadata_dao.get_amount_collector_by_mission_id(self.mission_id)

        if not collectors:
            self.messages.append("Can't find collectors for a given mission_id in the database")
            self.successful = False
            return

        collectors = list({i['uploaded_by']:i for i in reversed(collectors)}.values())
        collector_amount = 0
        collector_reward = 0
        storers = list()
        for doc in collectors:
            meta_public_address = doc["uploaded_by"]
            metadata_id = doc["_id"]
            meta_users = user_dao.get_user_by_public_address_claim(meta_public_address, UserRoleType.User)
            if len(meta_users) > 0:
                collector_amount += 1
                collector_reward = meta_users[0]["rewards"]
            
            entity_lists = entity_list_dao.get_entity_lists_by_entity_id(metadata_id)
            for entity in entity_lists:
                entity_public_address = entity["public_address"]
                
                entity_users = user_dao.get_user_by_public_address_claim(entity_public_address, UserRoleType.Storer)
                
                if len(entity_users) > 0:
                    storers.append({"public_address":entity_public_address})
                
        storers = list({i['public_address']:i for i in reversed(storers)}.values())
        storer_amount = len(storers)
        self.successful = True
        return {'mission_id': self.mission_id, 'collector_amount': collector_amount, 
        'storer_amount': storer_amount, 'collector_reward' : collector_reward}
