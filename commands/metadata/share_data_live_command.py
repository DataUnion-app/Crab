from commands.base_command import BaseCommand
from models.User import DataSharingOption
from dao.users_dao import user_dao

class ShareDataLiveCommand(BaseCommand):

    def __init__(self, public_address: str, data_sharing_option: DataSharingOption):
        super().__init__(public_address=public_address)
        self.data_sharing_option = data_sharing_option
        self.user_dao = user_dao

    def execute(self):
        self.successful = True
        result = user_dao.set_or_update_data_sharing_option(self.public_address, self.data_sharing_option)
        
        return result


class GetShareDataLiveCommand(BaseCommand):

    def __init__(self, public_address: str):
        super().__init__(public_address=public_address)
        self.user_dao = user_dao

    def execute(self):
        self.successful = True
        result = user_dao.get_data_sharing_option(self.public_address)
        
        return result
