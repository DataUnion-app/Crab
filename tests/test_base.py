import unittest
from io import BytesIO
from eth_account import Account
from PIL import Image
from dao.static_data_dao import StaticDataDao, WordTypes
from dao.users_dao import UsersDao
from dao.sessions_dao import SessionsDao
from dao.metadata_dao import image_metadata_dao
from dao.taxonomy_dao import TaxonomyDao
from dao.challenges_dao import ChallengesDao
from dao.rewards_dao import rewards_dao
from dao.entity_list_dao import entity_list_dao
from dao.bounty_dao import bounty_dao
from dao.missions_dao import missions_dao

import json
import os
import shutil
import requests
from helpers.login import Login
from models.metadata.metadata_models import Source
from utils.get_project_dir import get_project_root
from config import config


class TestBase(unittest.TestCase):
    URL = "http://localhost:{}".format(config["application"]["port"])

    @staticmethod
    def generated_image(width=1200, height=720, color=(39, 103, 73)):
        stream = BytesIO()
        Image.new("RGB", (width, height), color).save(stream, "JPEG")
        stream.seek(0)
        return stream

    @staticmethod
    def generated_media():
        return BytesIO(b"DataUnion generated test media\n")

    def __init__(self, *args, **kwargs):
        super(TestBase, self).__init__(*args, **kwargs)
        self.url = "http://localhost:{}".format(config["application"]["port"])
        self.db_host = config["couchdb"]["db_host"]
        self.db_user = config["couchdb"]["user"]
        self.password = config["couchdb"]["password"]

        self.data_dir = os.path.join(get_project_root(), "data")
        self.dummy_data_path = os.path.join(get_project_root(), "tests", "data")

        self.image_metadata_dao = image_metadata_dao

        self.user_dao = UsersDao()
        self.user_dao.set_config(self.db_user, self.password, self.db_host, "users")

        self.sessions_dao = SessionsDao()
        self.sessions_dao.set_config(
            self.db_user, self.password, self.db_host, "sessions"
        )

        self.static_data_dao = StaticDataDao()
        self.static_data_dao.set_config(
            self.db_user, self.password, self.db_host, "static_data_db"
        )

        self.taxonomy_dao = TaxonomyDao()
        self.taxonomy_dao.set_config(
            self.db_user, self.password, self.db_host, "taxonomy"
        )

        self.challenges_dao = ChallengesDao()
        self.challenges_dao.set_config(
            self.db_user, self.password, self.db_host, "challenges"
        )

        self.missions_dao = missions_dao

        self.rewards_dao = rewards_dao
        self.bounty_dao = bounty_dao
        self.acct = Account.create()
        self.token = None

        self.default_accounts: [Account] = []
        self.default_tokens: [str] = []

        self.entity_list_dao = entity_list_dao
        self.dummy_data_path = os.path.join(get_project_root(), "tests", "data")
        self.staging_path = os.path.join(get_project_root(), "staging")
        self.sample_image_path = os.path.join(self.dummy_data_path, 'sample.png')

    def setUp(self):
        self.clear_data_directory()

        self.user_dao.delete_all_docs()
        self.sessions_dao.delete_all_docs()
        self.image_metadata_dao.delete_all_docs()
        self.taxonomy_dao.delete_all_docs()
        self.challenges_dao.delete_all_docs()
        self.rewards_dao.delete_all_docs()
        self.entity_list_dao.delete_all_docs()
        self.bounty_dao.delete_all_docs()
        self.missions_dao.delete_all_docs()
        self.static_data_dao.add_words(list("abcdefghijkl"), WordTypes.RECOMMENDED_WORDS)
        self.read_default_accounts()

    def tearDown(self):
        self.clear_data_directory()

        self.user_dao.delete_all_docs()
        self.sessions_dao.delete_all_docs()
        self.image_metadata_dao.delete_all_docs()
        self.taxonomy_dao.delete_all_docs()
        self.challenges_dao.delete_all_docs()
        self.rewards_dao.delete_all_docs()
        self.entity_list_dao.delete_all_docs()
        self.bounty_dao.delete_all_docs()
        self.missions_dao.delete_all_docs()

    def clear_data_directory(self):
        for filename in os.listdir(self.data_dir):
            file_path = os.path.join(self.data_dir, filename)
            if filename == ".gitkeep":
                continue
            try:
                if os.path.isfile(file_path) or os.path.islink(file_path):
                    os.unlink(file_path)
                elif os.path.isdir(file_path):
                    shutil.rmtree(file_path)
            except Exception as e:
                print("Failed to delete %s. Reason: %s" % (file_path, e))

        data_dir = os.path.join(get_project_root(), config["taxonomy"]["image_folder"])
        if os.path.exists(data_dir) and os.path.isdir(data_dir):
            shutil.rmtree(data_dir)
            os.makedirs(data_dir)

    def get_token(self):
        if not self.token:
            self.token = Login.register_and_login2(self.url, self.acct.address, self.acct.key)['access_token']
        return self.token

    def read_default_accounts(self):
        path = os.path.join(get_project_root(), "tests", "account_keys.txt")
        if os.path.isfile(path):
            with open(path) as test_accounts_file:
                for line in test_accounts_file:
                    account = Account.from_key(line)
                    self.default_accounts.append(account)
                    token = Login.register_and_login2(
                        self.url, account.address, account.key
                    )['access_token']
                    self.default_tokens.append(token)

    @staticmethod
    def get_token_for_account(acct, source: Source = Source.default):
        return Login.register_and_login2(TestBase.URL, acct.address, acct.key, source)['access_token']

    if __name__ == "__main__":
        unittest.main()
