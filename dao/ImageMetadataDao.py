import requests
from .BaseDao import BaseDao
import json
from datetime import datetime
from models.ImageStatus import ImageStatus


class ImageMetadataDao(BaseDao):

    def get_images_by_eth_address(self, eth_address, page=1, status=None, fields=None):
        query = {
            "sort": [
                {
                    "_id": "asc"
                }
            ],
            "limit": self.page_size,
            "skip": (page - 1) * self.page_size,
            "selector": {
                "_id": {
                    "$gt": None
                },
                "uploaded_by": eth_address
            },
            "fields": fields
        }
        if status:
            query["selector"]["status"] = status
        headers = {'Content-Type': 'application/json'}
        url = "http://{0}:{1}@{2}/{3}/_find".format(self.user, self.password, self.db_host, self.db_name)

        response = requests.request("POST", url, headers=headers, data=json.dumps(query))

        data = json.loads(response.text)["docs"]
        return {"result": data, "page": page, "page_size": self.page_size}

    def get_metadata_by_address(self, address, page=1):
        query = {
            "sort": [
                {
                    "_id": "asc"
                }
            ],
            "limit": self.page_size,
            "skip": (page - 1) * self.page_size,
            "selector": {
                "_id": {
                    "$gt": None
                },
                "tag_data": {
                    "$elemMatch": {
                        "uploaded_by": address
                    }
                }
            },
            "fields": [
                "_id",
                "tag_data"
            ]
        }
        headers = {'Content-Type': 'application/json'}
        url = "http://{0}:{1}@{2}/{3}/_find".format(self.user, self.password, self.db_host, self.db_name)

        response = requests.request("POST", url, headers=headers, data=json.dumps(query))

        data = json.loads(response.text)["docs"]
        return {"result": data, "page": page, "page_size": self.page_size}

    def get_all_eth_addresses(self):
        # TODO
        pass

    def add_metadata_for_image(self, public_address, photo_id, tags, description, other):
        document = self.get_doc_by_id(photo_id)
        document["updated_at"] = datetime.timestamp(datetime.now())

        user_tags = document.get("tag_data")

        tag_data = {"tags": tags,
                    "other": other,
                    "uploaded_by": public_address,
                    "created_at": datetime.timestamp(datetime.now()),
                    "description": description,
                    "updated_at": datetime.timestamp(datetime.now())}

        if user_tags is not None:
            found_index = -1
            for index, user_tag in enumerate(user_tags):
                if user_tag.get("uploaded_by") == public_address:
                    found_index = index
            if found_index == -1:
                document["tag_data"].append(tag_data)
            else:
                document["tag_data"][found_index]["tags"] = tags
                document["tag_data"][found_index]["other"] = other
                document["tag_data"][found_index]["updated_at"] = datetime.timestamp(datetime.now())

        else:
            document["tag_data"] = [tag_data]

        document["updated_at"] = datetime.timestamp(datetime.now())
        document["status"] = ImageStatus.AVAILABLE_FOR_TAGGING.name
        document["status_description"] = "Image verified. Metadata saved"
        result = self.update_doc(photo_id, document)
        return result

    def get_by_status(self, status):
        query = {"selector": {"_id": {"$gt": None}, "status": status},
                 "fields": ["filename", "other", "tags", "_id", "_rev"]}
        url = "http://{0}:{1}@{2}/{3}/_find".format(self.user, self.password, self.db_host, self.db_name)
        headers = {'Content-Type': 'application/json'}

        response = requests.request("POST", url, headers=headers, data=json.dumps(query))
        data = json.loads(response.text)["docs"]
        return {"result": data}

    def get_userdata(self, address):
        query = {"selector": {"_id": {"$gt": None}},
                 "fields": ["tags", "_id"]}
        url = "http://{0}:{1}@{2}/{3}/_find".format(self.user, self.password, self.db_host, self.db_name)
        headers = {'Content-Type': 'application/json'}

        response = requests.request("POST", url, headers=headers, data=json.dumps(query))
        data = json.loads(response.text)["docs"]
        return {"result": data}

    def marked_as_reported(self, address, photos):

        doc_ids = [photo["photo_id"] for photo in photos]

        query = {"selector": {"_id": {"$in": doc_ids}}}
        url = "http://{0}:{1}@{2}/{3}/_find".format(self.user, self.password, self.db_host, self.db_name)
        headers = {'Content-Type': 'application/json'}

        response = requests.request("POST", url, headers=headers, data=json.dumps(query))
        data = json.loads(response.text)["docs"]
        for document in data:
            reports = document.get("reports")
            if not reports:
                document["reports"] = [{"reported_by": address}]
            elif len([report for report in reports if report["reported_by"] == address]) == 0:
                document["reports"].append({"reported_by": address})

            self.update_doc(document["_id"], document)

    def query_metadata(self, status=None, skip_tagged=False, page=1):

        image_status = status if status else {"$gt": None}

        query = {"sort": [{"_id": "asc"}], "limit": self.page_size, "skip": (page - 1) * self.page_size,
                 "selector": {"_id": {"$gt": None}, "status": image_status},
                 "fields": ["filename", "_id", "_rev"]}
        url = "http://{0}:{1}@{2}/{3}/_find".format(self.user, self.password, self.db_host, self.db_name)
        headers = {'Content-Type': 'application/json'}

        response = requests.request("POST", url, headers=headers, data=json.dumps(query))
        data = json.loads(response.text)["docs"]
        return {"result": data}
