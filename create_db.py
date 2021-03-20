import requests
import json
from config import config


class InitiateDB:
    def __init__(self):
        self.user = config['couchdb']['user']
        self.password = config['couchdb']['password']
        self.db_host = config['couchdb']['db_host']

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

    def create_users_db(self):
        users_db = config['couchdb']['users_db']
        self.create_db(users_db)
        self.create_view(users_db)

    def create_sessions_db(self):
        sessions_db = config['couchdb']['sessions_db']
        self.create_db(sessions_db)
        self.create_view(sessions_db)

    def init(self):
        self.create_users_db()
        self.create_sessions_db()
        self.create_metadata_db()

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


if __name__ == '__main__':
    db_initiator = InitiateDB()
    db_initiator.init()
