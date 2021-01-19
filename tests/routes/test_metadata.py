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
        self.db_host = '127.0.0.1:5984'
        self.db_user = 'admin'
        self.password = 'admin'
        self.data_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                                     'data')
        super(TestMetadata, self).__init__(*args, **kwargs)

    def setUp(self):
        self.clear_data_directory()
        user_dao = UsersDao()
        user_dao.set_config("admin", "admin", "127.0.0.1:5984", "users")
        user_dao.delete_db()
        user_dao.create_db()

        sessions_dao = SessionsDao()
        sessions_dao.set_config("admin", "admin", "127.0.0.1:5984", "sessions")
        sessions_dao.delete_db()
        sessions_dao.create_db()

        image_metadata_dao = ImageMetadataDao()
        image_metadata_dao.set_config("admin", "admin", "127.0.0.1:5984", "metadata")
        image_metadata_dao.delete_db()
        image_metadata_dao.create_db()

    def tearDown(self):
        self.clear_data_directory()
        user_dao = UsersDao()
        user_dao.set_config("admin", "admin", "127.0.0.1:5984", "users")
        user_dao.delete_db()
        user_dao.create_db()

        sessions_dao = SessionsDao()
        sessions_dao.set_config("admin", "admin", "127.0.0.1:5984", "sessions")
        sessions_dao.delete_db()
        sessions_dao.create_db()

        image_metadata_dao = ImageMetadataDao()
        image_metadata_dao.set_config("admin", "admin", "127.0.0.1:5984", "metadata")
        image_metadata_dao.delete_db()
        image_metadata_dao.create_db()

    def test_add_image(self):
        acct = Account.create()
        token = Helper.login(acct.address, acct.key)
        headers = {'Authorization': 'Bearer {0}'.format(token)}

        api_url = self.url + "/api/v1/upload-file"

        payload = {'uploaded_by': acct.address}
        image_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'sample.png')
        with open(image_path, 'rb') as img:
            files = [
                ('file',
                 ('sample.png', img, 'image/png'))
            ]

            response = requests.request("POST", api_url, headers=headers, data=payload, files=files)
            self.assertTrue(response.status_code, 200)
            data = json.loads(response.text)
            image_id = data["id"]
            self.assertTrue(image_id is not None)

    def test_add_image_twice(self):
        acct = Account.create()
        token = Helper.login(acct.address, acct.key)
        headers = {'Authorization': 'Bearer {0}'.format(token)}

        api_url = self.url + "/api/v1/upload-file"

        payload = {'uploaded_by': acct.address}
        image_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'sample.png')

        with open(image_path, 'rb') as img:
            files = [
                ('file',
                 ('sample.png', img, 'image/png'))
            ]

            response = requests.request("POST", api_url, headers=headers, data=payload, files=files)
            self.assertTrue(response.status_code, 200)
            data = json.loads(response.text)
            image_id = data["id"]
            self.assertTrue(image_id is not None)

        image_path2 = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'sample2.png')
        with open(image_path2, 'rb') as img2:
            files2 = [
                ('file',
                 ('sample2.png', img2, 'image/png'))
            ]

            response = requests.request("POST", api_url, headers=headers, data=payload, files=files2)
            self.assertTrue(response.status_code, 400)
            data = json.loads(response.text)
            self.assertEqual(data, {"message": "The uploaded file already exists in the dataset."})

    def test_metadata_to_image(self):
        acct = Account.create()
        token = Helper.login(acct.address, acct.key)
        headers = {'Authorization': 'Bearer {0}'.format(token)}

        api_url = self.url + "/api/v1/upload-file"
        payload = {'uploaded_by': acct.address}
        image_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'sample.png')

        with open(image_path, 'rb') as img:
            files = [
                ('file',
                 ('sample.png', img, 'image/png'))
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

        result = metadata_dao.get_doc_by_id(image_id)['tag_data']

        self.assertEqual(1, len(result))
        self.assertEqual(['t1', 't2'], result[0].get('tags'))
        self.assertEqual({}, result[0].get('other'))
        self.assertEqual(acct.address, result[0].get('uploaded_by'))

        acct2 = Account.create()
        api_url = self.url + "/api/v1/upload"
        token2 = Helper.login(acct2.address, acct2.key)
        headers2 = {'Authorization': 'Bearer {0}'.format(token2)}
        data2 = {"photo_id": image_id, "timestamp": "", "other": {}, "tags": ["u1", "u2"]}
        response2 = requests.request("POST", api_url, headers=headers2, data=json.dumps(data2))
        self.assertTrue(response2.status_code, 200)

        result = metadata_dao.get_doc_by_id(image_id)['tag_data']

        self.assertEqual(2, len(result))
        self.assertEqual(['u1', 'u2'], result[1].get('tags'))
        self.assertEqual({}, result[0].get('other'))
        self.assertEqual(acct2.address, result[1].get('uploaded_by'))

    def test_get_all_metadata(self):
        acct = Account.create()
        token = Helper.login(acct.address, acct.key)
        headers = {'Authorization': 'Bearer {0}'.format(token)}

        api_url = self.url + "/api/v1/my-metadata"
        response = requests.request("GET", api_url, headers=headers, data=json.dumps({}))
        data = json.loads(response.text)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(data, {"result": [], "page": 1, "page_size": 100})

        api_url = self.url + "/api/v1/my-metadata?page=3"
        response = requests.request("GET", api_url, headers=headers, data=json.dumps({}))
        data = json.loads(response.text)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(data, {"result": [], "page": 3, "page_size": 100})

    def test_get_my_images(self):

        acct = Account.create()
        token = Helper.login(acct.address, acct.key)
        headers = {'Authorization': 'Bearer {0}'.format(token)}

        api_url = self.url + "/api/v1/my-images"
        response = requests.request("GET", api_url, headers=headers, data=json.dumps({}))
        data = json.loads(response.text)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(data, {"result": [], "page": 1, "page_size": 100})

        api_url = self.url + "/api/v1/my-images?page=30"
        response = requests.request("GET", api_url, headers=headers, data=json.dumps({}))
        data = json.loads(response.text)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(data, {"result": [], "page": 30, "page_size": 100})

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
