import unittest
from eth_account import Account
from dao.image_metadata_dao import ImageMetadataDao
import json
import os
import shutil
import requests
from tests.helper import Helper
from tests.test_base import TestBase


class TestMetadataBulkUpload(TestBase):

    def __init__(self, *args, **kwargs):
        self.db_host = ''
        self.data_dir = os.path.join(Helper.get_project_root(), 'data')
        self.dummy_data_path = os.path.join(Helper.get_project_root(), 'tests', 'data')
        super(TestMetadataBulkUpload, self).__init__(*args, **kwargs)

    def test_upload_zip(self):
        acct = Account.create()
        token = Helper.login(acct.address, acct.key)
        headers = {'Authorization': 'Bearer {0}'.format(token)}

        api_url = self.url + "/api/v1/bulk/upload-zip"

        payload = {'uploaded_by': acct.address}
        zip_path = os.path.join(self.dummy_data_path, 'data.zip')
        with open(zip_path, 'rb') as zip_file:
            files = [
                ('file',
                 ('data.zip', zip_file, 'application/zip'))
            ]

            response = requests.request("POST", api_url, headers=headers, data=payload, files=files)
            self.assertTrue(response.status_code, 200)
            data = json.loads(response.text)
            image_id = data["id"]
            self.assertTrue(image_id is not None)

    def test_upload_zip2(self):
        acct = Account.create()
        token = Helper.login(acct.address, acct.key)
        headers = {'Authorization': 'Bearer {0}'.format(token)}

        api_url = self.url + "/api/v1/bulk/upload-zip"

        payload = {'uploaded_by': acct.address}
        zip_path = os.path.join(self.dummy_data_path, 'data2.zip')
        with open(zip_path, 'rb') as zip_file:
            files = [
                ('file',
                 ('data2.zip', zip_file, 'application/zip'))
            ]

            response = requests.request("POST", api_url, headers=headers, data=payload, files=files)
            self.assertTrue(response.status_code, 200)
            data = json.loads(response.text)
            image_id = data["id"]
            self.assertTrue(image_id is not None)
            self.assertTrue(3, data['result'])

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
        data = {"photo_id": image_id, "timestamp": "", "other": {}, "tags": ["t1", "t2"]}
        response = requests.request("POST", api_url, headers=headers, data=json.dumps(data))
        self.assertTrue(response.status_code, 200)

        metadata_dao = ImageMetadataDao()
        metadata_dao.set_config("admin", "admin", "127.0.0.1:5984", "metadata")

        result = metadata_dao.get_doc_by_id(image_id)['tag_data']

        self.assertEqual(1, len(result))
        self.assertEqual(['t1', 't2'], result[0].get('tags'))
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
        self.assertEqual(acct2.address, result[1].get('uploaded_by'))

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
