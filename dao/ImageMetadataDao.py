import requests
from .BaseDao import BaseDao
import json


class ImageMetadataDao(BaseDao):

    def get_metadata_by_eth_address(self, eth_address):
        query = {"selector": {"_id": {"$gt": None}, "uploaded_by": eth_address}}
        headers = {'Content-Type': 'application/json'}
        url = "http://{0}:{1}@{2}/{3}/_find".format(self.user, self.password, self.db_host, self.db_name)

        response = requests.request("POST", url, headers=headers, data=json.dumps(query))

        data = json.loads(response.text)["docs"]
        return {"result": data}

    def get_all_eth_addresses(self):
        # TODO
        pass
