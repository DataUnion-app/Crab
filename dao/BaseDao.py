import abc
import requests
import json
import logging


class BaseDao(metaclass=abc.ABCMeta):
    user = None
    password = None
    db_host = None
    db_name = None

    def __init__(self):
        self.page_size = 100

    def set_config(self, user, password, db_host, db_name):
        self.user = user
        self.password = password
        self.db_host = db_host
        self.db_name = db_name

    def save(self, doc_id, data):
        url = "http://{0}:{1}@{2}/{3}/{4}".format(self.user, self.password, self.db_host,
                                                  self.db_name, doc_id)
        headers = {
            'Content-Type': 'application/json'
        }

        response = requests.request("PUT", url, headers=headers, data=json.dumps(data))
        return json.loads(response.text)

    def getAll(self):
        query = {"selector": {"_id": {"$gt": None}}}
        headers = {'Content-Type': 'application/json'}
        url = "http://{0}:{1}@{2}/{3}/_find".format(self.user, self.password, self.db_host, self.db_name)

        response = requests.request("POST", url, headers=headers, data=json.dumps(query))

        data = json.loads(response.text)["docs"]
        return {"result": data}

    def get_doc_by_id(self, id):
        url = "http://{0}:{1}@{2}/{3}/{4}".format(self.user, self.password, self.db_host, self.db_name, id)
        headers = {'Accept': 'application/json'}
        response = requests.request("GET", url, headers=headers)
        data = json.loads(response.text)
        return data

    def query_data(self, selector):
        headers = {'Content-Type': 'application/json'}
        url = "http://{0}:{1}@{2}/{3}/_find".format(self.user, self.password, self.db_host, self.db_name)
        response = requests.request("POST", url, headers=headers, data=json.dumps(selector))
        if response.status_code != 200:
            logging.info("Failed to query data from db [{}]. Reason [{}]".format(self.db_name, response.text.rstrip()))
        try:
            data = json.loads(response.text).get("docs")
            return {"result": data}
        except ValueError:
            return {"result": {}}

    def update_doc(self, doc_id, data):
        return self.save(doc_id, data)

    def delete_db(self):
        logging.debug("Deleting db [{}]".format(self.db_name))
        url = "http://{0}:{1}@{2}/{3}".format(self.user, self.password, self.db_host, self.db_name)
        payload = {}
        headers = {}
        response = requests.request("DELETE", url, headers=headers, data=payload)

    def create_db(self):
        logging.debug("Creating db [{}]".format(self.db_name))
        url = "http://{0}:{1}@{2}/{3}".format(self.user, self.password, self.db_host, self.db_name)
        payload = {}
        headers = {}
        response = requests.request("PUT", url, headers=headers, data=payload)
        if response.status_code == 201:
            return True
        return False

    def exists(self, doc_id):
        url = "http://{0}:{1}@{2}/{3}/{4}".format(self.user, self.password, self.db_host, self.db_name, doc_id)
        headers = {'Accept': 'application/json'}
        response = requests.request("GET", url, headers=headers)
        if response.status_code == 200:
            return True
        return False
