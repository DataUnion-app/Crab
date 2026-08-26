from commands.base_command import BaseCommand
from dao.users_dao import user_dao
from models.metadata.metadata_models import Source

class GetAggregatedDataUnverifiedCreatorCommand(BaseCommand):

    def __init__(self, creator_id: str):
        super(GetAggregatedDataUnverifiedCreatorCommand, self).__init__()
        self.creator_id = creator_id

    def execute(self):
        user = user_dao.get_doc_by_id(self.creator_id)
        if len(user) == 0:
            self.messages.append("Can't find creator_id")
            self.successful = False
            return
        
        # Get User Details
        creator_detail = {}
        public_address = user["public_address"]
        creator_detail["public_address"] = public_address
        creator_detail["profile"] = user.get("profile")
        creator_detail["status"] = user.get("status")
        creator_detail["avartar"] = user.get("reserved_avatars")

        doc = {}
        doc["creator_detail"] = creator_detail
        return doc