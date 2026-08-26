from commands.base_command import BaseCommand
from dao.entity_list_dao import entity_list_dao


class DeleteEntityListCommand(BaseCommand):

    def __init__(self, public_address: str, list_id: str):
        super(DeleteEntityListCommand, self).__init__(public_address=public_address)
        self.list_id = list_id

    def execute(self):
        # TODO: Validate user has passed own list id
        entity_list_dao.delete_list(self.list_id)
        self.successful = True
        return
