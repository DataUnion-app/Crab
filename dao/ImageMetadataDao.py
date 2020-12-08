import requests
from .BaseDao import BaseDao
import json
from datetime import datetime
from models.ImageStatus import ImageStatus


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

    def add_metadata_for_image(self, photo_id, tags, other):
        document = self.get_doc_by_id(photo_id)
        document["updated_at"] = datetime.timestamp(datetime.now())
        document["tags"] = tags
        document["other"] = other
        document["status"] = "metadata_added"
        document["status_description"] = "Image verified. Metadata saved"
        result = self.update_doc(photo_id, document)
        return result

    def get_by_status(self, status: ImageStatus):
        query = {"selector": {"_id": {"$gt": None}, "status": status},
                 "fields": ["filename", "other", "tags", "_id", "_rev"]}
        url = "http://{0}:{1}@{2}/{3}/_find".format(self.user, self.password, self.db_host, self.db_name)
        headers = {'Content-Type': 'application/json'}

        response = requests.request("POST", url, headers=headers, data=json.dumps(query))
        data = json.loads(response.text)["docs"]
        return {"result": data}

    def get_all_verified_metadata(self):
        return self.get_by_status(ImageStatus.VERIFIED)
