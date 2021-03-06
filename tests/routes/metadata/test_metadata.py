import unittest
from web3.auto import w3
from eth_account import Account
from eth_account.messages import defunct_hash_message, encode_defunct
from dao.users_dao import UsersDao
from dao.sessions_dao import SessionsDao
from dao.image_metadata_dao import ImageMetadataDao
import json
import os
import shutil
import requests

from helpers.load_dummy_data import DummyDataLoader
from tests.helper import Helper
from models.ImageStatus import ImageStatus
from tests.test_base import TestBase


class TestMetadata(TestBase):

    def __init__(self, *args, **kwargs):
        self.url = 'http://localhost:8080'
        self.db_host = '127.0.0.1:5984'
        self.db_user = 'admin'
        self.password = 'admin'
        self.data_dir = os.path.join(Helper.get_project_root(), 'data')
        self.dummy_data_path = os.path.join(Helper.get_project_root(), 'tests', 'data')
        self.image_metadata_dao = ImageMetadataDao()
        self.image_metadata_dao.set_config(self.db_user, self.password, self.db_host, "metadata")
        super(TestMetadata, self).__init__(*args, **kwargs)

    def test_add_image(self):
        acct = Account.create()
        token = Helper.login(acct.address, acct.key)
        headers = {'Authorization': 'Bearer {0}'.format(token)}

        api_url = self.url + "/api/v1/upload-file"

        payload = {'uploaded_by': acct.address}
        image_path = os.path.join(self.dummy_data_path, 'sample.png')
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
        image_path = os.path.join(self.dummy_data_path, 'sample.png')

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

        image_path2 = os.path.join(self.dummy_data_path, 'sample2.png')
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
        image_path = os.path.join(self.dummy_data_path, 'sample.png')

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
        data = {"photo_id": image_id, "timestamp": "", "other": {}, "tags": ["t1  ", "  t2", " t3\t "],
                "description": "test"}
        response = requests.request("POST", api_url, headers=headers, data=json.dumps(data))
        self.assertTrue(response.status_code, 200)

        metadata_dao = ImageMetadataDao()
        metadata_dao.set_config("admin", "admin", "127.0.0.1:5984", "metadata")

        result = metadata_dao.get_doc_by_id(image_id)['tag_data']

        self.assertEqual(1, len(result))
        self.assertEqual(['t1', 't2', 't3'], result[0].get('tags'))
        self.assertEqual(acct.address, result[0].get('uploaded_by'))
        self.assertEqual('test', result[0].get('description'))

        acct2 = Account.create()
        api_url = self.url + "/api/v1/upload"
        token2 = Helper.login(acct2.address, acct2.key)
        headers2 = {'Authorization': 'Bearer {0}'.format(token2)}
        data2 = {"photo_id": image_id, "timestamp": "", "tags": ["u1", "u2"]}
        response2 = requests.request("POST", api_url, headers=headers2, data=json.dumps(data2))
        self.assertTrue(response2.status_code, 200)

        result = metadata_dao.get_doc_by_id(image_id)['tag_data']

        self.assertEqual(2, len(result))
        self.assertEqual(['u1', 'u2'], result[1].get('tags'))
        self.assertEqual(acct2.address, result[1].get('uploaded_by'))
        self.assertIsNone(result[1].get('description'))

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

    def test_mark_as_reported(self):
        acct = Account.create()
        token = Helper.login(acct.address, acct.key)
        self.upload_zip(acct, token, 'data.zip')

        headers = {'Authorization': 'Bearer {0}'.format(token)}
        api_url = self.url + "/api/v1/report-images"
        data = {}
        response = requests.request("POST", api_url, headers=headers, data=json.dumps(data))

        self.assertEqual(400, response.status_code)
        self.assertEqual(
            {"message": "Invalid input body. Expected keys :{\'photos\'}", "status": "failed"},
            json.loads(response.text))

        acct = Account.create()
        token = Helper.login(acct.address, acct.key)
        headers = {'Authorization': 'Bearer {0}'.format(token)}
        images = self.image_metadata_dao.get_by_status(ImageStatus.VERIFIABLE.name)
        data = {"photos": [{"photo_id": image["_id"]} for image in images["result"]]}
        response = requests.request("POST", api_url, headers=headers, data=json.dumps(data))
        self.assertEqual(200, response.status_code)
        self.assertEqual({"status": "success"}, json.loads(response.text))

    def test_mark_as_reported2(self):

        dummy_data_loader = DummyDataLoader()
        image_id = dummy_data_loader.load_random_data2(1, 1, 500,500)[0]

        headers = {'Authorization': 'Bearer {0}'.format(self.get_token())}
        api_url = self.url + "/api/v1/report-images"
        data = {'photos': [{'photo_id': image_id}]}
        response = requests.request("POST", api_url, headers=headers, data=json.dumps(data))

        self.assertEqual(200, response.status_code)
        doc = self.image_metadata_dao.get_doc_by_id(image_id)
        self.assertEqual(ImageStatus.REPORTED_AS_INAPPROPRIATE.name, doc['status'])

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

    def upload_zip(self, account=None, token=None, filename='data.zip'):
        if not account or not token:
            account = Account.create()
            token = Helper.login(account.address, account.key)
        headers = {'Authorization': 'Bearer {0}'.format(token)}

        api_url = self.url + "/api/v1/bulk/upload-zip"

        payload = {'uploaded_by': account.address}
        zip_path = os.path.join(self.dummy_data_path, filename)
        with open(zip_path, 'rb') as zip_file:
            files = [
                ('file',
                 (filename, zip_file, 'application/zip'))
            ]

            response = requests.request("POST", api_url, headers=headers, data=payload, files=files)
            self.assertTrue(response.status_code, 200)
            data = json.loads(response.text)
            image_id = data["id"]
            self.assertTrue(image_id is not None)

    if __name__ == '__main__':
        unittest.main()
