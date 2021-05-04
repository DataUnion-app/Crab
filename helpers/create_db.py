import requests
import json
import os
from config import config
from commands.staticdata.add_words import AddWordsCommand, WordTypes
from utils.get_project_dir import get_project_root
from helpers.add_words import load_words_from_file


class InitiateDB:
    def __init__(self):
        self.user = config['couchdb']['user']
        self.password = config['couchdb']['password']
        self.db_host = config['couchdb']['db_host']

    def init(self):
        self.create_users_db()
        self.create_sessions_db()
        self.create_metadata_db()
        self.create_static_data_db()
        self.create_taxonomy_db()

        self.create_db(config['couchdb']['challenges_db'])
        self.create_db("_users")
        self.create_db("_session")

    def create_db(self, db_name):
        print("Creating [{0}] db".format(db_name))
        url = "http://{0}:{1}@{2}/{3}".format(self.user, self.password, self.db_host, db_name)
        response = requests.request("PUT", url, headers={}, data=json.dumps({}))
        print(response.text)

    def create_metadata_db(self):
        metadata_db = config['couchdb']['metadata_db']
        self.create_db(metadata_db)
        self.create_view(metadata_db)

        url = "http://{0}:{1}@{2}/{3}/_index".format(self.user, self.password, self.db_host, metadata_db)
        body = {
            "index": {
                "fields": ["uploaded_by"]
            },
            "name": "uploaded_by-index",
            "type": "json"
        }
        headers = {
            'Content-Type': 'application/json'
        }

        response = requests.request("POST", url, headers=headers, data=json.dumps(body))
        print(response.text)

        body = {
            "index": {
                "fields": ["uploaded_at"]
            },
            "name": "uploaded_at-index",
            "type": "json"
        }
        headers = {
            'Content-Type': 'application/json'
        }

        response = requests.request("POST", url, headers=headers, data=json.dumps(body))
        print(response.text)

        path = os.path.join('helpers', 'db_setup', 'metadata_views.json')
        with open(path) as json_file:
            data = json.load(json_file)
            self.create_views(metadata_db, data['views'])

    def create_users_db(self):
        users_db = config['couchdb']['users_db']
        self.create_db(users_db)
        self.create_view(users_db)
        self.create_doc_count_view(users_db)

    def create_taxonomy_db(self):
        taxonomy_db = config['couchdb']['taxonomy_db']
        self.create_db(taxonomy_db)
        self.create_view(taxonomy_db)
        self.create_doc_count_view(taxonomy_db)

        url = "http://{0}:{1}@{2}/{3}/_index".format(self.user, self.password, self.db_host, taxonomy_db)
        body = {
            "index": {
                "fields": ["created_at"]
            },
            "name": "created_at-index",
            "type": "json"
        }
        headers = {
            'Content-Type': 'application/json'
        }

        response = requests.request("POST", url, headers=headers, data=json.dumps(body))
        print(response.text)

    def create_sessions_db(self):
        sessions_db = config['couchdb']['sessions_db']
        self.create_db(sessions_db)
        self.create_view(sessions_db)

    def create_static_data_db(self):
        static_data_db = config['couchdb']['static_data_db']
        self.create_db(static_data_db)
        self.create_view(static_data_db)

        root = get_project_root()
        file_path1 = os.path.join(root, "helpers", "data", "staticdata", "banned_words.txt")
        load_words_from_file(file_path1, WordTypes.BANNED_WORDS)

        file_path2 = os.path.join(root, "helpers", "data", "staticdata", "recommended_words.txt")
        load_words_from_file(file_path2, WordTypes.RECOMMENDED_WORDS)

    def create_view(self, db_name):
        print("Creating all-docs view for [{0}]".format(db_name))
        body = {
            "_id": "_design/all-docs",
            "views": {
                "all-docs": {
                    "map": "function (doc) {\n  emit(doc._id, {\"rev\":doc._rev, \"id\": doc._id});\n}"
                }
            },
            "language": "javascript"
        }

        headers = {
            'Content-Type': 'application/json'
        }

        url = "http://{0}:{1}@{2}/{3}".format(self.user, self.password, self.db_host, db_name)
        response = requests.request("POST", url, headers=headers, data=json.dumps(body))
        print(response.text)

    def create_doc_count_view(self, db_name):
        print("Creating doc_count_view for [{0}]".format(db_name))
        body = {"_id": "_design/counts",
                "language": "javascript",
                "views": {
                    "all": {
                        "map": "function(doc) { emit(null, 1); }",
                        "reduce": "function(keys, values, combine) { return sum(values); }"
                    }
                }
                }

        headers = {'Content-Type': 'application/json'}
        url = "http://{0}:{1}@{2}/{3}".format(self.user, self.password, self.db_host, db_name)
        response = requests.request("POST", url, headers=headers, data=json.dumps(body))
        print(response.text)

    def create_views(self, db_name, views):
        for view in views:
            print("Creating [{0}] for [{1}]".format(db_name, view['_id']))
            body = view
            headers = {'Content-Type': 'application/json'}
            url = "http://{0}:{1}@{2}/{3}".format(self.user, self.password, self.db_host, db_name)
            response = requests.request("POST", url, headers=headers, data=json.dumps(body))
            print(response.text)


if __name__ == '__main__':
    db_initiator = InitiateDB()
    db_initiator.init()
