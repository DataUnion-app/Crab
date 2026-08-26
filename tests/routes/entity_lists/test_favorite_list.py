import json

import requests

from models.entity_list_models import EntityListType
from models.metadata.metadata_models import EntityType
from tests.test_base import TestBase


class TestFavoriteEntityLists(TestBase):

    def test_manage_favorite_entity_lists(self):
        public_address = self.default_accounts[0].address
        elist_id1 = self.entity_list_dao.create_list(public_address,
                                                     EntityType.image, ["123"],
                                                     EntityListType.PUBLIC,
                                                     'test')
        elist_id2 = self.entity_list_dao.create_list(public_address,
                                                     EntityType.image,
                                                     ["123"],
                                                     EntityListType.PRIVATE,
                                                     'test')

        token = self.default_tokens[0]
        headers = {"Authorization": "Bearer {0}".format(token)}

        api_url = f"{self.url}/api/v1/entity-lists/manage-favorites"
        data = {
            "entity_lists_to_mark": [elist_id1, elist_id2],
            "entity_lists_to_unmark": [elist_id2]
        }

        response = requests.request("POST", api_url, headers=headers, data=json.dumps(data))

        self.assertEqual(200, response.status_code)

    def test_get_favorite_entity_lists(self):
        public_address = self.default_accounts[0].address
        elist_id1 = self.entity_list_dao.create_list(public_address,
                                                     EntityType.image, ["123"],
                                                     EntityListType.PUBLIC,
                                                     'test')
        elist_id2 = self.entity_list_dao.create_list(public_address,
                                                     EntityType.image,
                                                     ["123"],
                                                     EntityListType.PRIVATE,
                                                     'test')

        token = self.default_tokens[0]
        headers = {"Authorization": "Bearer {0}".format(token)}

        api_url = f"{self.url}/api/v1/entity-lists/manage-favorites"
        data = {
            "entity_lists_to_mark": [elist_id1, elist_id2],
            "entity_lists_to_unmark": [elist_id1]
        }
        requests.request("POST", api_url, headers=headers, data=json.dumps(data))

        api_url = f"{self.url}/api/v1/entity-lists/favorites"
        response = requests.request("GET", api_url, headers=headers)

        self.assertEqual(200, response.status_code)
        self.assertEqual(len(response.json()['result']['private_favorites_list']), 1)
