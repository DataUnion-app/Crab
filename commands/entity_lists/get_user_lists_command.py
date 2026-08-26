from commands.base_command import BaseCommand
from dao.base_dao import DBResultError
from dao.entity_list_dao import entity_list_dao
from models.metadata.metadata_models import EntityType


class GetUserListsCommand(BaseCommand):
    def __init__(self, public_address: str, page: int, entity_type: EntityType):
        super(GetUserListsCommand, self).__init__(public_address=public_address)
        self.page = page
        self.entity_type = entity_type

    def execute(self):
        try:
            user_lists = entity_list_dao.get_user_lists(self.public_address, self.entity_type, self.page)
            start_key = end_key = f"[\"{self.public_address}\",\"{self.entity_type}\"]"
            count = entity_list_dao.query_view_by_key_range("user-created-lists", "count-by-user-and-type", start_key,
                                                            end_key, 2)["rows"][0]["value"]

            result = [{'id': l["_id"], 'entity_ids': l['entity_ids'], 'entity_list_type': l['entity_list_type'],
                       'name': l['name'], 'description': l['description'], 'image': l.get('image')} for l
                      in user_lists]

        except DBResultError as e:
            self.messages.append(str(e))
            return

        self.successful = True
        return count, result


class GetListById(BaseCommand):
    def __init__(self, list_id: str):
        super(GetListById, self).__init__()
        self.list_id = list_id

    def execute(self):
        self.successful = True
        r = entity_list_dao.get_doc_by_id(self.list_id)
        result = {'id': r["_id"], 'entity_ids': r['entity_ids'], 'entity_list_type': r['entity_list_type'],
                  'name': r['name'], 'description': r['description']}
        return result
