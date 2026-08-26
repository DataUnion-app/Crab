from commands.base_command import BaseCommand
from dao.users_dao import user_dao
from models.metadata.metadata_models import Source

class GetAggregatedDataUnverifiedStorerCommand(BaseCommand):

    def __init__(self, storer_id: str):
        super(GetAggregatedDataUnverifiedStorerCommand, self).__init__()
        self.storer_id = storer_id

    def execute(self):
        user = user_dao.get_doc_by_id(self.storer_id)
        if len(user) == 0:
            self.messages.append("Can't find storer_id")
            self.successful = False
            return
        
        # Get Storer Details
        storer_details = {}
        public_address = user["public_address"]
        storer_details["public_address"] = public_address
        storer_details["profile"] = user.get("profile")
        storer_details["status"] = user.get("status")
        storer_details["avartar"] = user.get("reserved_avatars")

        doc = {}
        doc["storer_details"] = storer_details
        return doc