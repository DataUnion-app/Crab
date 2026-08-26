import json

import requests
from eth_account import Account

from models.entity_list_models import EntityListType
from models.metadata.metadata_models import EntityType
from tests.dummy_data_helper import DummyDataHelper
from tests.test_base import TestBase


class TestEntityLists(TestBase):
    def test_create_entity_list(self):
        public_address = self.default_accounts[0].address
        docs_id1 = self.image_metadata_dao.add_new_image_entity("123", public_address, "123.png", "123.png", 10, 10, [])
        docs_id2 = self.image_metadata_dao.add_new_image_entity("abc", public_address, "123.png", "123.png", 10, 10, [])

        token = self.default_tokens[0]
        headers = {"Authorization": "Bearer {0}".format(token)}
        api_url = self.url + "/api/v1/entity-lists/create"
        data = {
            "entity_ids": [docs_id1, docs_id2],
            "visibility": "public",
            "entity_type": "image",
        }
        response = requests.request(
            "POST", api_url, headers=headers, data=json.dumps(data)
        )
        self.assertEqual(200, response.status_code)

        docs = self.entity_list_dao.get_all()["result"]
        self.assertEqual(1, len(docs))

    def test_create_entity_list2(self):
        token = self.default_tokens[0]
        headers = {"Authorization": "Bearer {0}".format(token)}
        api_url = self.url + "/api/v1/entity-lists/create"
        data = {
            "entity_ids": [123, "abc"],
            "visibility": "public",
            "entity_type": "image",
        }
        response = requests.request(
            "POST", api_url, headers=headers, data=json.dumps(data)
        )
        self.assertEqual(400, response.status_code)
        messages = json.loads(response.text)["messages"]
        self.assertListEqual(["Invalid 'entity_ids'"], messages)

    def test_create_entity_list3(self):
        public_address = self.default_accounts[0].address
        docs_id1 = self.image_metadata_dao.add_new_image_entity("123", public_address, "123.png", "123.png", 10, 10, [])
        docs_id2 = self.image_metadata_dao.add_new_video_entity("abc", public_address, "123.png", "123.png", [])

        token = self.default_tokens[0]
        headers = {"Authorization": "Bearer {0}".format(token)}
        api_url = self.url + "/api/v1/entity-lists/create"
        data = {
            "entity_ids": [docs_id1, docs_id2],
            "visibility": "public",
            "entity_type": "image",
        }
        response = requests.request(
            "POST", api_url, headers=headers, data=json.dumps(data)
        )
        self.assertEqual(400, response.status_code)

        messages = json.loads(response.text)["messages"]
        self.assertListEqual(["Invalid entity_type for the given entity_ids"], messages)

    def test_delete_entity_list(self):
        public_address = self.default_accounts[0].address
        list_id = self.entity_list_dao.create_list(public_address, EntityType.image, ["123"], EntityListType.PUBLIC,
                                                   'test')

        token = self.default_tokens[0]
        headers = {"Authorization": "Bearer {0}".format(token)}
        api_url = f"{self.url}/api/v1/entity-lists/?id={list_id}"

        response = requests.request("DELETE", api_url, headers=headers, data={})
        self.assertEqual(200, response.status_code)

        docs = self.entity_list_dao.get_all()["result"]
        self.assertEqual(0, len(docs))
        self.assertEqual({'id': list_id}, json.loads(response.text))

    def test_get_user_lists(self):
        public_address = self.default_accounts[0].address
        self.entity_list_dao.create_list(public_address, EntityType.image, ["123"], EntityListType.PUBLIC, 'test')
        self.entity_list_dao.create_list(public_address, EntityType.image, ["123"], EntityListType.PUBLIC, 'test')

        token = self.default_tokens[0]
        headers = {"Authorization": "Bearer {0}".format(token)}
        api_url = f"{self.url}/api/v1/entity-lists/own?page=1&entity_type={EntityType.image}"

        response = requests.request("GET", api_url, headers=headers, data={})
        self.assertEqual(200, response.status_code)

        result = json.loads(response.text)["result"]
        self.assertEqual(2, len(result))
        self.assertListEqual(['description', 'entity_ids', 'entity_list_type', 'id', 'image', 'name'],
                             list(result[0].keys()))

    def test_update_list(self):
        public_address = self.default_accounts[0].address
        list_id = self.entity_list_dao.create_list(public_address, EntityType.image, ["123"], EntityListType.PUBLIC,
                                                   'test', 'desc1')

        token = self.default_tokens[0]
        headers = {"Authorization": "Bearer {0}".format(token)}
        api_url = f"{self.url}/api/v1/entity-lists/update"

        data = {
            "entity_ids": ['xyz', 'abc'],
            "visibility": "public",
            "id": list_id,
            'description': 'desc2',
            'name': 'test2'
        }
        response = requests.request(
            "POST", api_url, headers=headers, data=json.dumps(data)
        )

        self.assertEqual(200, response.status_code)

        document = self.entity_list_dao.get_doc_by_id(list_id)
        self.assertEqual('desc2', document['description'])
        self.assertEqual('test2', document['name'])

        self.assertListEqual(['xyz', 'abc'], document['entity_ids'])

    def test_search_list(self):
        public_address = self.default_accounts[0].address
        self.entity_list_dao.create_list(public_address, EntityType.image, ["123"], EntityListType.PUBLIC, 'test')
        self.entity_list_dao.create_list(public_address, EntityType.image, ["abc"], EntityListType.PRIVATE, 'test')

        api_url = f"{self.url}/api/v1/entity-lists/search?page=1&entity_type={EntityType.image}"

        response = requests.request("GET", api_url, headers={}, data={})
        self.assertEqual(200, response.status_code)

        result = json.loads(response.text)["result"]
        self.assertEqual(1, len(result))
        self.assertListEqual(['description', 'entity_ids', 'id', 'image', 'name'], list(result[0].keys()))

    def test_create_list_from_text_tags(self):
        public_address = self.default_accounts[0].address

        DummyDataHelper.add_random_image(public_address=public_address, tags=["abc"])
        DummyDataHelper.add_random_image(public_address=public_address, tags=["123"])

        token = self.default_tokens[0]
        headers = {"Authorization": "Bearer {0}".format(token)}
        api_url = self.url + "/api/v1/entity-lists/create-from-annotations"
        data = {
            "annotation_type": "TextTag",
            "tags": ["abc"],
            "visibility": "public",
            "entity_type": "image",
        }
        response = requests.request(
            "POST", api_url, headers=headers, data=json.dumps(data)
        )
        self.assertEqual(200, response.status_code)

        docs = self.entity_list_dao.get_all()["result"]
        self.assertEqual(1, len(docs))

    def test_edit_list_from_text_tags(self):
        public_address = self.default_accounts[0].address

        list_id = self.entity_list_dao.create_list(public_address, EntityType.image, ["123"], EntityListType.PUBLIC,
                                                   'test', 'desc1')

        DummyDataHelper.add_random_image(public_address=public_address, tags=["abc"])
        DummyDataHelper.add_random_image(public_address=public_address, tags=["123"])

        token = self.default_tokens[0]
        headers = {"Authorization": "Bearer {0}".format(token)}
        api_url = self.url + "/api/v1/entity-lists/create-from-annotations"
        data = {
            "annotation_type": "TextTag",
            "tags": ["abc"],
            "entity_list_id": list_id
        }
        response = requests.request(
            "POST", api_url, headers=headers, data=json.dumps(data)
        )
        self.assertEqual(200, response.status_code)

        docs = self.entity_list_dao.get_all()["result"]
        self.assertEqual(1, len(docs))

        token2 = self.get_token()
        response2 = requests.request("POST", api_url, headers={"Authorization": "Bearer {0}".format(token2)},
                                     data=json.dumps(data))
        self.assertEqual(400, response2.status_code)

    def test_merge_entity_list(self):
        public_address = self.default_accounts[0].address
        list_1 = self.entity_list_dao.create_list(public_address, EntityType.image, ["123", "a"], EntityListType.PUBLIC,
                                                  'test')
        list_2 = self.entity_list_dao.create_list(public_address, EntityType.image, ["123"], EntityListType.PUBLIC,
                                                  'test')
        list_3 = self.entity_list_dao.create_list(public_address, EntityType.image, ["123"], EntityListType.PRIVATE,
                                                  'test')
        token = self.default_tokens[0]
        headers = {"Authorization": "Bearer {0}".format(token)}
        api_url = self.url + "/api/v1/entity-lists/merge"
        data = {
            "sources": [list_1],
            "destination": list_2,
        }
        response = requests.request(
            "POST", api_url, headers=headers, data=json.dumps(data)
        )
        self.assertEqual(200, response.status_code)
        merged_list = self.entity_list_dao.get_doc_by_id(list_2)
        self.assertEqual(["123", "a"], sorted(merged_list["entity_ids"]))

        # Do not allow non-owner to merge
        account = Account.create()
        t2 = self.get_token_for_account(account)

        headers = {"Authorization": "Bearer {0}".format(t2)}
        data = {
            "sources": [list_1],
            "destination": list_2,
        }
        response = requests.request(
            "POST", api_url, headers=headers, data=json.dumps(data)
        )
        self.assertEqual(400, response.status_code)

        # Do not allow non-owner to read private list
        list_4 = self.entity_list_dao.create_list(account.address, EntityType.image, ["123"], EntityListType.PRIVATE,
                                                  'test')
        headers = {"Authorization": "Bearer {0}".format(t2)}
        data = {
            "source": list_3,  # private list
            "destination": list_4,
        }
        response = requests.request(
            "POST", api_url, headers=headers, data=json.dumps(data)
        )
        self.assertEqual(400, response.status_code)
