from commands.base_command import BaseCommand
from dao.entity_list_dao import entity_list_dao


class FavoriteEntityListsMarkCommand(BaseCommand):

    def __init__(self, user_address: str, marked_list: list, unmarked_list: list):
        super(FavoriteEntityListsMarkCommand, self).__init__()
        self.user_address = user_address
        self.marked_list = marked_list
        self.unmarked_list = unmarked_list

    def execute(self):
        if not self.marked_list and not self.unmarked_list:
            self.successful = False
            self.messages.append('Either entity_lists_to_mark or entity_lists_to_unmark should exist')
            return

        for m_entity_id in self.marked_list:
            m_entity_list_obj = entity_list_dao.get_doc_by_id(m_entity_id)
            favorites_of = m_entity_list_obj.get('favorites_of', [])

            if self.user_address not in favorites_of:
                if m_entity_list_obj.get('entity_list_type', '') == 'private' and \
                   m_entity_list_obj.get('public_address', '') != self.user_address:
                   continue
                favorites_of.append(self.user_address)
                entity_list_dao.update_doc(m_entity_id, m_entity_list_obj)
        for um_entity_id in self.unmarked_list:
            um_entity_list_obj = entity_list_dao.get_doc_by_id(um_entity_id)
            unfavorites_of = um_entity_list_obj.get('favorites_of', [])
            
            if self.user_address in unfavorites_of:
                if um_entity_list_obj.get('entity_list_type', '') == 'private' and \
                   um_entity_list_obj.get('public_address', '') != self.user_address:
                   continue
                unfavorites_of.remove(self.user_address)
                entity_list_dao.update_doc(um_entity_id, um_entity_list_obj)

        self.successful = True


class GetFavoriteEntityListsCommand(BaseCommand):

    def __init__(self, user_address: str):
        super(GetFavoriteEntityListsCommand, self).__init__()
        self.user_address = user_address

    def execute(self):
        if not self.user_address:
            self.successful = False
            self.messages.append('The User address can not be empty')
            return {}
        
        favorite_entity_lists = entity_list_dao.get_favorite_entities(self.user_address)
        public_ids = [i['_id'] for i in favorite_entity_lists if i['entity_list_type'] == 'public']
        private_ids = [i['_id'] for i in favorite_entity_lists if i['entity_list_type'] == 'private']

        self.successful = True
        return {
            'public_favorites_list': public_ids,
            'private_favorites_list': private_ids
        }
