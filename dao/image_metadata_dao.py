import json
from datetime import datetime
import requests

from config import config
from dao.base_dao import BaseDao
from models.ImageStatus import ImageStatus
import logging


class ImageMetadataDao(BaseDao):

    def __init__(self):
        super().__init__()
        self.threshold_verifiable = 3
        self.threshold_verified = 3

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

    def add_description_for_image(self, public_address: str, image_id: str, description: str):
        document = self.get_doc_by_id(image_id)
        document["updated_at"] = datetime.timestamp(datetime.now())

        text_annotations = document.get("text_annotations")

        text_data = {"text": description,
                     "uploaded_by": public_address,
                     "created_at": datetime.timestamp(datetime.now()),
                     "updated_at": datetime.timestamp(datetime.now())}

        if text_annotations is not None:
            found_index = -1
            for index, user_text in enumerate(text_annotations):
                if user_text.get("uploaded_by") == public_address:
                    found_index = index
            if found_index == -1:
                document["text_annotations"].append(text_data)
            else:
                document["text_annotations"][found_index]["text"] = description
                document["text_annotations"][found_index]["updated_at"] = datetime.timestamp(datetime.now())

        else:
            document["text_annotations"] = [text_data]

        document["updated_at"] = datetime.timestamp(datetime.now())
        result = self.update_doc(image_id, document)
        return result

    def add_tags_for_image(self, public_address: str, image_id: str, tags: [str]):
        document = self.get_doc_by_id(image_id)
        document["updated_at"] = datetime.timestamp(datetime.now())

        tags_annotations = document.get("tags_annotations")

        tag_data = {"tags": tags,
                    "uploaded_by": public_address,
                    "created_at": datetime.timestamp(datetime.now()),
                    "updated_at": datetime.timestamp(datetime.now())}

        if tags_annotations is not None:
            found_index = -1
            for index, user_tag in enumerate(tags_annotations):
                if user_tag.get("uploaded_by") == public_address:
                    found_index = index
            if found_index == -1:
                document["tags_annotations"].append(tag_data)
            else:
                document["tags_annotations"][found_index]["tags"] = tags
                document["tags_annotations"][found_index]["updated_at"] = datetime.timestamp(datetime.now())

        else:
            document["tags_annotations"] = [tag_data]

        document["updated_at"] = datetime.timestamp(datetime.now())
        result = self.update_doc(image_id, document)
        return result

    def move_to_verifiable_if_possible(self, photo_id):
        document = self.get_doc_by_id(photo_id)
        tag_data = document.get("tag_data")
        if len(tag_data) >= self.threshold_verifiable:
            document["updated_at"] = datetime.timestamp(datetime.now())
            document["status"] = ImageStatus.VERIFIABLE.name
            self.update_doc(photo_id, document)

    def move_to_verified_if_possible(self, photo_id):
        query_string = "/_design/verification/_view/verification-view?key=\"{0}\"&limit=1".format(
            photo_id)
        url = "http://{0}:{1}@{2}/{3}/{4}".format(self.user, self.password, self.db_host, self.db_name, query_string)
        response = requests.request("GET", url, headers={}, data=json.dumps({}))

        if response.status_code == 200:
            data = json.loads(response.text)
            if len(data['rows']) == 1 and data['rows'][0]['value'].get('can_be_marked_as_verified'):
                document = self.get_doc_by_id(photo_id)
                document["updated_at"] = datetime.timestamp(datetime.now())
                document["status"] = ImageStatus.VERIFIED.name
                self.update_doc(photo_id, document)
        else:
            logging.error("Could not check if verified [%s]" % photo_id)

    def get_by_status(self, status):
        query = {"selector": {"_id": {"$gt": None}, "status": status},
                 "fields": ["filename", "other", "tags", "_id", "_rev"]}
        url = "http://{0}:{1}@{2}/{3}/_find".format(self.user, self.password, self.db_host, self.db_name)
        headers = {'Content-Type': 'application/json'}

        response = requests.request("POST", url, headers=headers, data=json.dumps(query))
        data = json.loads(response.text)["docs"]
        return {"result": data}

    def get_userdata(self, address):
        query = {"selector": {"_id": address},
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
            document["status"] = ImageStatus.REPORTED_AS_INAPPROPRIATE.name
            self.update_doc(document["_id"], document)

    def query_metadata(self, status, page, fields):
        skip = 0
        if page > 1:
            skip = (page - 1) * 100
        query_url = '/_design/query-metadata/_view/query-metadata?startkey=["{0}"]&limit={1}&skip={2}&sorted=true'.format(
            status,
            self.page_size, skip)

        url = "http://{0}:{1}@{2}/{3}/{4}".format(self.user, self.password, self.db_host, self.db_name, query_url)
        headers = {'Content-Type': 'application/json'}

        response = requests.request("GET", url, headers=headers, data={})
        data = json.loads(response.text)

        result = list(map(lambda row: {field: row["value"].get(field) for field in fields}, data["rows"]))

        return {"result": result, "page": page, "page_size": self.page_size}

    def query_tags(self, status, page, public_address):

        skip = 0
        if page > 1:
            skip = (page - 1) * 100

        selector = {
            "selector": {
                "status": status,
                "$and": [
                    {
                        "$not": {
                            "uploaded_by": public_address
                        }
                    },
                    {
                        "$not": {
                            "tag_data": {
                                "$elemMatch": {
                                    "uploaded_by": {
                                        "$eq": public_address
                                    }
                                }
                            }
                        }
                    },
                    {
                        "$not": {
                            "verified": {
                                "$elemMatch": {
                                    "by": {
                                        "$eq": public_address
                                    }
                                }
                            }
                        }
                    }
                ]
            },
            "sort": [
                {
                    "uploaded_at": "desc"
                }
            ],
            "fields": [
                "_id",
                "tag_data",
                "verified"
            ],
            "limit": self.page_size,
            "skip": skip
        }

        data = self.query_data(selector)['result']
        result = []
        for row in data:

            tag_data = []
            descriptions = []
            for tagged_data in row['tag_data']:
                if tagged_data['description']:
                    descriptions.append(tagged_data['description'])
                tag_data = tag_data + tagged_data['tags']

            for verified in row['verified']:
                tag_data = tag_data + verified['tags']['up_votes']
                tag_data = tag_data + verified['tags']['down_votes']
                if verified.get('descriptions'):
                    descriptions = descriptions + verified['descriptions'].get('up_votes', [])
                    descriptions = descriptions + verified['descriptions'].get('down_votes', [])
            result.append({
                'image_id': row['_id'],
                'tag_data': list(set(tag_data)),
                'descriptions': list(set(descriptions))
            })
        return {"result": result, "page": page, "page_size": self.page_size}

    def mark_as_verified(self, data, public_address: str):
        image_ids = [row['image_id'] for row in data]
        query = {"selector": {"_id": {"$in": image_ids}}, "limit": len(image_ids)}
        url = "http://{0}:{1}@{2}/{3}/_find".format(self.user, self.password, self.db_host, self.db_name)
        headers = {'Content-Type': 'application/json'}

        response = requests.request("POST", url, headers=headers, data=json.dumps(query))
        documents = json.loads(response.text)["docs"]
        result = []
        for document in documents:
            if document['status'] not in [ImageStatus.VERIFIABLE.name, ImageStatus.VERIFIED.name]:
                result.append({'image_id': document['_id'], 'success': False})
                continue
            verified = document.get("verified")

            tag_up_votes = []
            tag_down_votes = []
            description_up_votes = []
            description_down_votes = []
            for row in data:
                if row['image_id'] == document['_id']:
                    tag_up_votes = row['tags']['up_votes']
                    tag_down_votes = row['tags']['down_votes']
                    description_up_votes = row['descriptions']['up_votes']
                    description_down_votes = row['descriptions']['down_votes']
                    break

            verified_data = {"by": public_address, "time": datetime.timestamp(datetime.now()),
                             'tags': {'up_votes': tag_up_votes, 'down_votes': tag_down_votes},
                             'descriptions': {'up_votes': description_up_votes, 'down_votes': description_down_votes}}

            if not verified:
                document["verified"] = [verified_data]
            elif len([report for report in verified if report["by"] == public_address]) == 0:
                document["verified"].append(verified_data)
            self.update_doc(document["_id"], document)
            result.append({'image_id': document['_id'], 'success': True})
        return result

    def exists(self, doc_id):
        selector = {
            "selector": {
                "$or": [
                    {
                        "hash": doc_id
                    },
                    {
                        "qr_code_hash": doc_id
                    }
                ]
            },
            "limit": 1,
            "fields": ["hash", "qr_code_hash"]
        }
        result = self.query_data(selector)['result']
        if len(result) == 0:
            return False
        return True

    def get_tag_stats(self):
        query_url = '/_design/stats-verification/_view/stats-verification'

        url = "http://{0}:{1}@{2}/{3}/{4}".format(self.user, self.password, self.db_host, self.db_name, query_url)
        headers = {'Content-Type': 'application/json'}
        response = requests.request("GET", url, headers=headers, data={})
        data = json.loads(response.text)['rows']
        if len(data) == 0:
            return {
                "desc_down_votes": 0, "desc_up_votes": 0, "tags_down_votes": 0, "tags_up_votes": 0
            }
        else:
            return data[0]['value']

    def my_tags(self, public_address: str, start_time: float, end_time: float):
        selector = {
            "selector": {
                "type": "image",
                "verified": {
                    "$elemMatch": {
                        "by": {
                            "$eq": public_address
                        }
                    }
                },
                "$and": [
                    {
                        "verified": {
                            "$elemMatch": {
                                "time": {
                                    "$gte": start_time
                                }
                            }
                        }
                    },
                    {
                        "verified": {
                            "$elemMatch": {
                                "time": {
                                    "$lte": end_time
                                }
                            }
                        }
                    }
                ]
            },
            "sort": [
                {
                    "uploaded_at": "desc"
                }
            ],
            "fields": [
                "_id",
                "verified"
            ],
        }

        docs = self.query_all(selector)
        result = []
        for doc in docs:
            verified = doc['verified']
            verification = list(filter(lambda v: v['by'] == public_address, verified))[0]
            tags_up_votes = verification['tags'].get('up_votes')
            tags_down_votes = verification['tags'].get('down_votes')
            descriptions_up_votes = verification['descriptions'].get('up_votes')
            descriptions_down_votes = verification['descriptions'].get('down_votes')

            result.append({'image_id': doc['_id'], 'tags_up_votes': tags_up_votes,
                           'tags_down_votes': tags_down_votes, 'descriptions_up_votes': descriptions_up_votes,
                           'descriptions_down_votes': descriptions_down_votes, 'time': verification['time']})

        result.sort(key=lambda x: x['time'])
        return result


image_metadata_dao = ImageMetadataDao()
image_metadata_dao.set_config(config['couchdb']['user'], config['couchdb']['password'], config['couchdb']['db_host'],
                              config['couchdb']['metadata_db'])
