import requests
from .BaseDao import BaseDao
import json


class ImageMetadataDao(BaseDao):

    def save(self, doc_id, data):

        url = "http://{0}:{1}@{2}/{3}/{4}".format(self.user,self.password,self.db_host,
                                                                  self.db_name,doc_id)
        headers = {
            'Content-Type': 'application/json'
        }

        response = requests.request("PUT", url, headers=headers, data=json.dumps(data))
        return json.loads(response.text)

    def getAll(self):

        url = "http://{0}:{1}@{2}/{3}/_all_docs".format(self.user, self.password, self.db_host, self.db_name)

        response = requests.request("GET", url, headers={}, data={})
        return json.loads(response.text)
