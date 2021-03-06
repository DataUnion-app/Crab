import unittest
from eth_account import Account

from dao.static_data_dao import StaticDataDao
from dao.users_dao import UsersDao
from dao.sessions_dao import SessionsDao
from dao.image_metadata_dao import ImageMetadataDao
from dao.taxonomy_dao import TaxonomyDao
import json
import os
import shutil
import requests
from tests.helper import Helper
from config import config
from utils.get_project_dir import get_project_root


class TestBase(unittest.TestCase):

    def __init__(self, *args, **kwargs):
        self.url = 'http://localhost:8080'
        self.db_host = config['couchdb']['db_host']
        self.db_user = config['couchdb']['user']
        self.password = config['couchdb']['password']

        self.data_dir = os.path.join(Helper.get_project_root(), 'data')
        self.dummy_data_path = os.path.join(Helper.get_project_root(), 'tests', 'data')

        self.image_metadata_dao = ImageMetadataDao()
        self.image_metadata_dao.set_config(self.db_user, self.password, self.db_host, "metadata")

        self.user_dao = UsersDao()
        self.user_dao.set_config(self.db_user, self.password, self.db_host, "users")

        self.sessions_dao = SessionsDao()
        self.sessions_dao.set_config(self.db_user, self.password, self.db_host, "sessions")

        self.static_data_dao = StaticDataDao()
        self.static_data_dao.set_config(self.db_user, self.password, self.db_host, "staticdata")

        self.taxonomy_dao = TaxonomyDao()
        self.taxonomy_dao.set_config(self.db_user, self.password, self.db_host, "taxonomy")

        self.acct = Account.create()
        self.token = None

        self.default_accounts: [Account] = []
        self.default_tokens: [str] = []

        self.read_default_accounts()

        super(TestBase, self).__init__(*args, **kwargs)

    def setUp(self):
        self.clear_data_directory()

        self.user_dao.delete_all_docs()
        self.sessions_dao.delete_all_docs()
        self.image_metadata_dao.delete_all_docs()
        self.taxonomy_dao.delete_all_docs()

    def tearDown(self):
        self.clear_data_directory()

        self.user_dao.delete_all_docs()
        self.sessions_dao.delete_all_docs()
        self.image_metadata_dao.delete_all_docs()
        self.taxonomy_dao.delete_all_docs()

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

        data_dir = os.path.join(get_project_root(), config['taxonomy']['image_folder'])
        if os.path.exists(data_dir) and os.path.isdir(data_dir):
            shutil.rmtree(data_dir)
            os.makedirs(data_dir)

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

    def get_token(self):
        if not self.token:
            self.token = Helper.login(self.acct.address, self.acct.key)
        return self.token

    def read_default_accounts(self):
        path = os.path.join(get_project_root(), 'tests', 'account_keys.txt')
        if os.path.isfile(path):
            with open(path) as test_accounts_file:
                for line in test_accounts_file:
                    account = Account.from_key(line)
                    self.default_accounts.append(account)
                    self.default_tokens.append(Helper.login(account.address, account.key))

    if __name__ == '__main__':
        unittest.main()
