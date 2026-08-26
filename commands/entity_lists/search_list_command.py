from commands.base_command import BaseCommand
from dao.base_dao import DBResultError
from dao.entity_list_dao import entity_list_dao
from models.entity_list_models import EntityListType
from models.metadata.metadata_models import EntityType


class SearchListCommand(BaseCommand):

    def __init__(self, entity_type: EntityType, entity_list_id: str, page: int = 1):
        super(SearchListCommand, self).__init__()
        self.entity_type = entity_type
        self.page = page
        self.entity_list_id = entity_list_id

    def execute(self):
        lists = entity_list_dao.get_all_public_lists(self.entity_type, self.entity_list_id, self.page)

        result = [{'id': item['_id'], 'entity_ids': item['entity_ids'], 'description': item['description'],
                   'name': item['name'], 'image': item.get("image")} for item in
                  lists]

        self.successful = True
        return result


class SearchListByIdCommand(BaseCommand):

    def __init__(self, public_address: str, entity_list_id: str):
        super(SearchListByIdCommand, self).__init__(public_address)
        self.entity_list_id = entity_list_id

    def execute(self):
        try:
            document = entity_list_dao.get_doc_by_id(self.entity_list_id)

            if document['entity_list_type'] == EntityListType.PRIVATE and \
                document['public_address'] != self.public_address:
                self.successful = False
                self.messages.append("Access to list denied.")
                return

            result = {'id': document['_id'], 'entity_ids': document['entity_ids'],
                      'description': document['description'], 'entity_list_type': document['entity_list_type'],
                      'name': document['name'], 'image': document.get("image")}
        except DBResultError as e:
            self.successful = False
            self.messages.append(str(e))
            return

        self.successful = True
        return result
