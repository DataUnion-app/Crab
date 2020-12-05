import abc
import requests
import json


class BaseDao(metaclass=abc.ABCMeta):

    user = None
    password = None
    db_host = None
    db_name = None

    def set_config(self, user, password, db_host, db_name):
        self.user = user
        self.password = password
        self.db_host = db_host
        self.db_name = db_name

    def save(self, doc_id, data):

        url = "http://{0}:{1}@{2}/{3}/{4}".format(self.user,self.password,self.db_host,
                                                  self.db_name,doc_id)
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

# @abc.abstractmethod
    # def delete(self, id):
    #     pass
    #
    # @abc.abstractmethod
    # def update(self, id):
    #     pass
    #
    # @abc.abstractmethod
    # def get(self, id):
    #     pass
    #
