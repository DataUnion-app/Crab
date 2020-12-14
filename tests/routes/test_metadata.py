import unittest
from web3.auto import w3
from eth_account import Account
from eth_account.messages import defunct_hash_message, encode_defunct
from dao.users_dao import UsersDao
from dao.sessions_dao import SessionsDao
from dao.ImageMetadataDao import ImageMetadataDao
import json
import os
import shutil
import requests
from tests.helper import Helper


class TestMetadata(unittest.TestCase):

    def __init__(self, *args, **kwargs):
        self.url = 'http://localhost:8080'
        self.db_host = ''
        self.data_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                                     'data')
        super(TestMetadata, self).__init__(*args, **kwargs)

    @classmethod
    def setUpClass(cls):
        user_dao = UsersDao()
        user_dao.set_config("admin", "admin", "127.0.0.1:5984", "users")
        user_dao.create_db()

        sessions_dao = SessionsDao()
        sessions_dao.set_config("admin", "admin", "127.0.0.1:5984", "sessions")
        sessions_dao.create_db()

    @classmethod
    def tearDownClass(cls):
        user_dao = UsersDao()
        user_dao.set_config("admin", "admin", "127.0.0.1:5984", "users")
        user_dao.delete_db()

        sessions_dao = SessionsDao()
        sessions_dao.set_config("admin", "admin", "127.0.0.1:5984", "sessions")
        sessions_dao.delete_db()

    def setUp(self):
        pass
        self.clear_data_directory()

    def tearDown(self):
        self.clear_data_directory()
        pass

    def test_add_image(self):
        acct = Account.create('TEST')
        token = Helper.login(acct.address, acct.key)
        headers = {'Authorization': 'Bearer {0}'.format(token)}

        api_url = self.url + "/api/v1/upload-file"

        payload = {'uploaded_by': acct.address}
        image_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'sample.png')

        files = [
            ('file',
             ('sample.png', open(image_path, 'rb'), 'image/png'))
        ]

        response = requests.request("POST", api_url, headers=headers, data=payload, files=files)
        self.assertTrue(response.status_code, 200)
        data = json.loads(response.text)
        image_id = data["id"]
        self.assertTrue(image_id is not None)

    def test_metadata_to_image(self):
        acct = Account.create('TEST')
        token = Helper.login(acct.address, acct.key)
        headers = {'Authorization': 'Bearer {0}'.format(token)}

        api_url = self.url + "/api/v1/upload-file"
        payload = {'uploaded_by': acct.address}
        image_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'sample.png')
        files = [
            ('file',
             ('sample.png', open(image_path, 'rb'), 'image/png'))
        ]

        response = requests.request("POST", api_url, headers=headers, data=payload, files=files)
        self.assertTrue(response.status_code, 200)
        data = json.loads(response.text)
        image_id = data["id"]
        self.assertTrue(image_id is not None)

        api_url = self.url + "/api/v1/upload"
        data = {"photo_id": image_id, "timestamp": "", "other": {}, "tags": ["t1", "t2"]}
        response = requests.request("POST", api_url, headers=headers, data=json.dumps(data))
        self.assertTrue(response.status_code, 200)

        metadata_dao = ImageMetadataDao()
        metadata_dao.set_config("admin", "admin", "127.0.0.1:5984", "metadata")

        result = metadata_dao.get_doc_by_id(image_id)
        self.assertEqual(result['tags'], ['t1', 't2'])
        self.assertEqual(result['other'], {})

    def clear_data_directory(self):
        for filename in os.listdir(self.data_dir):
            file_path = os.path.join(self.data_dir, filename)
            if filename == '.gitkeep':
                continue
            try:
                if os.path.isfile(file_path) or os.path.islink(file_path):
                    os.unlink(file_path)
                elif os.path.isdir(file_path):
                    shutil.rmtree(file_path)
            except Exception as e:
                print('Failed to delete %s. Reason: %s' % (file_path, e))


if __name__ == '__main__':
    unittest.main()
