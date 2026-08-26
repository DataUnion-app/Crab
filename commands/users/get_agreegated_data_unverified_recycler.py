from commands.base_command import BaseCommand
from dao.users_dao import user_dao
from models.metadata.metadata_models import Source

class GetAggregatedDataUnverifiedRecyclerCommand(BaseCommand):

    def __init__(self, recycler_id: str):
        super(GetAggregatedDataUnverifiedRecyclerCommand, self).__init__()
        self.recycler_id = recycler_id

    def execute(self):
        user = user_dao.get_doc_by_id(self.recycler_id)
        if len(user) == 0:
            self.messages.append("Can't find recycler_id")
            self.successful = False
            return
        
        # Get User Details
        recycler_detail = {}
        public_address = user["public_address"]
        recycler_detail["public_address"] = public_address
        recycler_detail["profile"] = user.get("profile")
        recycler_detail["status"] = user.get("status")
        recycler_detail["avartar"] = user.get("reserved_avatars")

        doc = {}
        doc["recycler_detail"] = recycler_detail
        return doc