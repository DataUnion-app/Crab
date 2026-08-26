from commands.base_command import BaseCommand
from models.entity_list_models import EntityListType
from dao.entity_list_dao import entity_list_dao


class UpdateEntityListCommand(BaseCommand):

    def __init__(self, public_address: str, list_id: str, entity_ids: list, entity_list_type: EntityListType, name: str,
                 description: str = None, image: str = None):
        super(UpdateEntityListCommand, self).__init__(public_address=public_address)
        self.entity_ids = entity_ids
        self.entity_list_type = entity_list_type
        self.description = description
        self.list_id = list_id
        self.name = name
        self.image = image

    def execute(self):
        # TODO: Validate new list
        description_limit = 2000
        if self.description and len(self.description) > description_limit:
            self.messages.append(f"Description too long. Limit is {description_limit} characters.")
            return

        name_limit = 200
        if self.description and len(self.name) > name_limit:
            self.messages.append(f"Name too long. Limit is {name_limit} characters.")
            return

        entity_list_dao.update_list(self.list_id, self.entity_ids, self.entity_list_type, self.name, self.description, self.image)
        self.successful = True
        return


class UpdateBountyProgressCommand(BaseCommand):
    def __init__(self):
        super(UpdateBountyProgressCommand, self).__init__()

    def execute(self):
        pass
