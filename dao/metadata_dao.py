import json
import logging
import os
from datetime import datetime
from typing import List, Optional, Any


import utils.get_random_string
from config import config
from dao.base_dao import BaseDao, DBResultError
from dao.bounty_dao import bounty_dao
from models.ImageStatus import ImageStatus
from models.metadata.annotations.annotation_type import AnnotationType
from models.metadata.annotations.base_annotation import BaseAnnotation
from models.metadata.annotations.text_description import DescriptionAnnotation
from models.metadata.annotations.text_tag import TagAnnotation
from models.metadata.metadata_models import EntityType, EntitySubType, MonetizationStatus, Network, Source, EntityRewardStatus
from models.User import UserRoleType


class ImageMetadataDao(BaseDao):
    def __init__(self):
        super().__init__()
        self.threshold_verifiable = 3
        self.threshold_verified = 3

    def get_images_by_eth_address(self, eth_address, page=1, status=None, fields=None):
        query = {
            "sort": [{"_id": "asc"}],
            "limit": self.page_size,
            "skip": (page - 1) * self.page_size,
            "selector": {"_id": {"$gt": None}, "uploaded_by": eth_address},
            "fields": fields,
        }
        if status:
            query["selector"]["status"] = status
        headers = {"Content-Type": "application/json"}
        url = f"{self.base_url}/_find"

        response = self.client.request(
            "POST", url, headers=headers, data=json.dumps(query)
        )

        data = json.loads(response.text)["docs"]
        return {"result": data, "page": page, "page_size": self.page_size}

    def get_metadata_by_address(self, address, page=1):
        query = {
            "sort": [{"_id": "asc"}],
            "limit": self.page_size,
            "skip": (page - 1) * self.page_size,
            "selector": {
                "_id": {"$gt": None},
                "tag_data": {"$elemMatch": {"uploaded_by": address}},
            },
            "fields": ["_id", "tag_data"],
        }
        headers = {"Content-Type": "application/json"}
        url = f"{self.base_url}/_find"

        response = self.client.request(
            "POST", url, headers=headers, data=json.dumps(query)
        )

        data = json.loads(response.text)["docs"]
        return {"result": data, "page": page, "page_size": self.page_size}

    def get_missions_by_public_address(self, public_address):
        query = {
            "selector": {
                "_id": {"$gt": None},
                "uploaded_by": public_address,
            },
            "fields": ["mission_id"],
        }
        headers = {"Content-Type": "application/json"}
        url = f"{self.base_url}/_find"

        response = self.client.request(
            "POST", url, headers=headers, data=json.dumps(query)
        )
        data = json.loads(response.text)["docs"]
        result= []
        for mission_id in data:
            result.append(mission_id.get('mission_id'))
        result = set(result)

        return result
    
    def get_bounties_by_public_address(self, public_address):
        query = {
            "selector": {
                "_id": {"$gt": None},
                "uploaded_by": public_address,
            },
            "fields": ["bounty_id"],
        }
        headers = {"Content-Type": "application/json"}
        url = f"{self.base_url}/_find"

        response = self.client.request(
            "POST", url, headers=headers, data=json.dumps(query)
        )
        data = json.loads(response.text)["docs"]
        result= []
        for bounty_id in data:
            result.append(bounty_id.get('bounty_id'))
        result = set(result)

        return result

    def get_metadata_by_public_address(self, public_address):
        query = {
            "selector": {
                "_id": {"$gt": None},
                "uploaded_by": public_address,
            },
        }
        headers = {"Content-Type": "application/json"}
        url = f"{self.base_url}/_find"

        response = self.client.request(
            "POST", url, headers=headers, data=json.dumps(query)
        )
        data = json.loads(response.text)["docs"]

        return data

    def get_all_eth_addresses(self):
        # TODO
        pass

    def get_original_image_path(self, image_id: str):
        document = self.get_doc_by_id(image_id)
        return document["image_path"]

    def add_description_for_image(
            self, public_address: str, image_id: str, description: str
    ) -> str:
        description_annotation = DescriptionAnnotation(public_address, image_id, description)
        self.add_annotation_to_image(image_id, [description_annotation])
        return description_annotation.annotation_id

    def add_tags_for_image(self, public_address: str, image_id: str, tags: [str]) -> str:
        tags_annotation = TagAnnotation(public_address, image_id, tags)
        self.add_annotation_to_image(image_id, [tags_annotation])
        return tags_annotation.annotation_id

    def move_to_verifiable_if_possible(self, photo_id):
        document = self.get_doc_by_id(photo_id)
        tag_data = document.get("tag_data")
        if len(tag_data) >= self.threshold_verifiable:
            document["updated_at"] = datetime.timestamp(datetime.utcnow())
            document["status"] = ImageStatus.VERIFIABLE.name
            self.update_doc(photo_id, document)

    def move_to_verified_if_possible(self, photo_id):
        query_string = (
            '/_design/verification/_view/verification-view?key="{0}"&limit=1'.format(
                photo_id
            )
        )
        url = f"{self.base_url}{query_string}"
        response = self.client.request("GET", url, headers={}, data=json.dumps({}))

        if response.status_code == 200:
            data = json.loads(response.text)
            if len(data["rows"]) == 1 and data["rows"][0]["value"].get(
                    "can_be_marked_as_verified"
            ):
                document = self.get_doc_by_id(photo_id)
                document["updated_at"] = datetime.timestamp(datetime.utcnow())
                document["status"] = ImageStatus.VERIFIED.name
                self.update_doc(photo_id, document)
        else:
            logging.error("Could not check if verified [%s]" % photo_id)

    def get_by_status(self, status):
        query = {
            "selector": {"_id": {"$gt": None}, "status": status},
            "fields": ["filename", "other", "tags", "_id", "_rev"],
        }
        url = f"{self.base_url}/_find"
        headers = {"Content-Type": "application/json"}

        response = self.client.request(
            "POST", url, headers=headers, data=json.dumps(query)
        )
        data = json.loads(response.text)["docs"]
        return {"result": data}

    def get_userdata(self, address):
        query = {"selector": {"_id": address}, "fields": ["tags", "_id"]}
        url = f"{self.base_url}/_find"
        headers = {"Content-Type": "application/json"}

        response = self.client.request(
            "POST", url, headers=headers, data=json.dumps(query)
        )
        data = json.loads(response.text)["docs"]
        return {"result": data}

    def marked_as_reported(self, address: str, photos, threshold: int):
        doc_ids = [photo["photo_id"] for photo in photos]

        query = {"selector": {"_id": {"$in": doc_ids}}}
        url = f"{self.base_url}/_find"
        headers = {"Content-Type": "application/json"}

        response = self.client.request(
            "POST", url, headers=headers, data=json.dumps(query)
        )
        data = json.loads(response.text)["docs"]
        for document in data:
            reports = document.get("reports")
            if not reports:
                document["reports"] = [{"reported_by": address}]
            elif (
                    len([report for report in reports if report["reported_by"] == address])
                    == 0
            ):
                document["reports"].append({"reported_by": address})

            if len(document["reports"]) >= threshold:
                document["status"] = ImageStatus.REPORTED_AS_INAPPROPRIATE.name

            self.update_doc(document["_id"], document)

    def query_ids_for_mission(self, public_address: str, page: int) -> object:
        result = None
        return {"result": result}

    def query_ids_not_annotated_by_user(self, status: str, page: int, public_address: str,
                                        annotation_type: AnnotationType, bounty: str, doc_type: str = "image",
                                        tags: [str] = None, ) -> object:
        skip = 0
        if page > 1:
            skip = (page - 1) * 100

        selector = {
            "status": status,
            "type": doc_type,
            "$nor": [
                {
                    "uploaded_by": public_address
                },
                {
                    "annotations": {
                        "$elemMatch": {
                            "public_address": public_address,
                            "type": annotation_type
                        }
                    }
                }
            ],
            "bounty": {"$in": [bounty]}
        }

        if tags:
            selector["annotations"] = {
                "$elemMatch": {
                    "type": AnnotationType.TextTag,
                    "tags": {
                        "$in":
                            tags

                    }
                }
            }

        if AnnotationType.TextTag == annotation_type:
            selector["$nor"].append({
                "verified": {
                    "$elemMatch": {
                        "by": public_address
                    }
                }
            })
        query = {
            "selector": selector,
            "sort": [{"uploaded_at": "desc"}],
            "fields": ["_id", "annotations"],
            "limit": self.page_size,
            "skip": skip,
        }

        data = self.query_data(query)["result"]
        result = []
        for row in data:
            tag_data = []
            tag_annotations = [x for x in row["annotations"] if x["type"] == AnnotationType.TextTag]
            for tagged_data in tag_annotations:
                tag_data = tag_data + tagged_data["tags"]

            descriptions = []
            text_annotations = [x for x in row["annotations"] if x["type"] == AnnotationType.TextDescription]

            for text_data in text_annotations:
                descriptions.append(text_data["text"])

            result.append(
                {
                    "image_id": row["_id"],
                    "tag_data": list(set(tag_data)),
                    "descriptions": list(set(descriptions)),
                }
            )
        return {"result": result, "page": page, "page_size": self.page_size}

    def mark_image_as_verified(self, image_id, data, public_address: str) -> Optional[str]:

        document = self.get_doc_by_id(image_id)
        if document["status"] not in [
            ImageStatus.VERIFIABLE.name,
            ImageStatus.VERIFIED.name,
        ]:
            return None

        verified = document.get("verified")

        tag_up_votes = data["tags"].get("up_votes")
        tag_down_votes = data["tags"].get("down_votes")
        description_up_votes = data["descriptions"].get("up_votes")
        description_down_votes = data["descriptions"].get("down_votes")
        verification_id = 'verification:' + utils.get_random_string.get_random_string(10)
        verified_data = {
            'id': verification_id,
            "by": public_address,
            "time": datetime.timestamp(datetime.utcnow()),
            "tags": {"up_votes": tag_up_votes, "down_votes": tag_down_votes},
            "descriptions": {
                "up_votes": description_up_votes,
                "down_votes": description_down_votes,
            },
        }

        if not verified:
            document["verified"] = [verified_data]
        elif len([v for v in verified if v["by"] == public_address]) == 0:
            document["verified"].append(verified_data)

        self.update_doc(document["_id"], document)
        return verification_id

    def exists(self, doc_id):
        selector = {
            "selector": {"$or": [{"hash": doc_id}, {"qr_code_hash": doc_id}, {"_id": doc_id}]},
            "limit": 1,
            "fields": ["hash", "qr_code_hash"],
        }
        result = self.query_data(selector)["result"]
        if len(result) == 0:
            return False
        return True

    def get_tag_stats(self, data_type: str, start_date: datetime, end_date: datetime):
        start_key = f"[\"{data_type}\",{start_date.year},{start_date.month},{start_date.day}]"
        end_key = f"[\"{data_type}\",{end_date.year},{end_date.month},{end_date.day},{{}}]"
        query_url = f"/_design/stats/_view/tags-stats-view?start_key={start_key}&end_key={end_key}&group_level=5"

        url = f"{self.base_url}{query_url}"
        headers = {"Content-Type": "application/json"}
        response = self.client.request("GET", url, headers=headers, data={})
        data = json.loads(response.text)["rows"]

        result = {}
        for row in data:
            year = row["key"][1]
            month = row["key"][2]
            date = row["key"][3]
            tag = row["key"][4]

            if tag not in result:
                result[tag] = []

            value = row["value"]
            result[tag].append({"date": f"{date}-{month}-{year}", "value": value})
        return result

    def my_tags(self, public_address: str, start_time: float, end_time: float):
        selector = {
            "selector": {
                "type": "image",
                "verified": {"$elemMatch": {"by": {"$eq": public_address}}},
                "$and": [
                    {"verified": {"$elemMatch": {"time": {"$gte": start_time}}}},
                    {"verified": {"$elemMatch": {"time": {"$lte": end_time}}}},
                ],
            },
            "sort": [{"uploaded_at": "desc"}],
            "fields": ["_id", "verified"],
        }

        docs = self.query_all(selector)
        result = []
        for doc in docs:
            verified = doc["verified"]
            verification = list(filter(lambda v: v["by"] == public_address, verified))[
                0
            ]
            tags_up_votes = verification["tags"].get("up_votes")
            tags_down_votes = verification["tags"].get("down_votes")
            descriptions_up_votes = verification["descriptions"].get("up_votes")
            descriptions_down_votes = verification["descriptions"].get("down_votes")

            result.append(
                {
                    "image_id": doc["_id"],
                    "tags_up_votes": tags_up_votes,
                    "tags_down_votes": tags_down_votes,
                    "descriptions_up_votes": descriptions_up_votes,
                    "descriptions_down_votes": descriptions_down_votes,
                    "time": verification["time"],
                }
            )

        result.sort(key=lambda x: x["time"])
        return result

    def get_user_stats(
            self, data_type: str, public_address: str, start_date: datetime, end_date: datetime
    ):
        start_key = f'[\"{data_type}\","{public_address}",{start_date.year},{start_date.month},{start_date.day}]'
        end_key = (
            f'[\"{data_type}\","{public_address}",{end_date.year},{end_date.month},{end_date.day},{{}}]'
        )

        query_url = f"/_design/stats/_view/user-stats-view?start_key={start_key}&end_key={end_key}&group_level=6"

        url = f"{self.base_url}{query_url}"
        headers = {"Content-Type": "application/json"}
        payload = {}
        response = self.client.request("GET", url, headers=headers, data=payload)
        if response.status_code != 200:
            raise DBResultError(self.db_name, response.text)

        data = json.loads(response.text)
        result = {}
        for row in data["rows"]:
            year = row["key"][2]
            month = row["key"][3]
            date = row["key"][4]
            op_type = row["key"][5]

            if op_type not in result:
                result[op_type] = []

            value = row["value"]
            result[op_type].append(
                {
                    "date": datetime.strptime(
                        f"{date}-{month}-{year}", "%d-%m-%Y"
                    ).strftime("%d-%m-%Y"),
                    "value": value,
                }
            )

        if "tag_annotations" not in result:
            result["tag_annotations"] = []

        if "text_annotations" not in result:
            result["text_annotations"] = []

        if "uploads" not in result:
            result["uploads"] = []

        if "verifications" not in result:
            result["verifications"] = []

        if "pixel_annotations" not in result:
            result["pixel_annotations"] = []
        return result

    def get_overall_stats(self, data_type: str, start_date: datetime, end_date: datetime):
        start_key = f"[\"{data_type}\",{start_date.year},{start_date.month},{start_date.day}]"
        end_key = f"[\"{data_type}\",{end_date.year},{end_date.month},{end_date.day},{{}}]"

        query_url = f"/_design/stats/_view/overall-stats-view?start_key={start_key}&end_key={end_key}&group_level=5"

        url = f"{self.base_url}{query_url}"
        headers = {"Content-Type": "application/json"}
        payload = {}
        response = self.client.request("GET", url, headers=headers, data=payload)

        data = json.loads(response.text)
        result = {}
        for row in data["rows"]:
            year = row["key"][1]
            month = row["key"][2]
            date = row["key"][3]
            op_type = row["key"][4]

            if op_type not in result:
                result[op_type] = []

            value = row["value"]
            result[op_type].append(
                {
                    "date": datetime.strptime(
                        f"{date}-{month}-{year}", "%d-%m-%Y"
                    ).strftime("%d-%m-%Y"),
                    "value": value,
                }
            )

        if "tag_annotations" not in result:
            result["tag_annotations"] = []

        if "text_annotations" not in result:
            result["text_annotations"] = []

        if "uploads" not in result:
            result["uploads"] = []

        if "verifications" not in result:
            result["verifications"] = []

        if "pixel_annotations" not in result:
            result["pixel_annotations"] = []
        return result

    def search_entity_by_status(self, page: int, entity_type: str, status: str) -> [str]:
        skip = (page - 1) * self.page_size
        url = (
            f"{self.base_url}/_design/query-metadata/_view/search-by-status?"
            f"key=[\"{entity_type}\",\"{status}\"]&limit={self.page_size}&skip={skip}&sorted=true&reduce=false"
        )

        response = self.client.request("GET", url)

        if response.status_code != 200:
            logging.exception(response.text)
            raise DBResultError(self.db_name, response.text)

        return {
            "data": [i["value"] for i in response.json()["rows"]],
            "page": page,
            "page_size": self.page_size
        }
    
    def search_entity_by_location(self, entity_type: str,longitude: float, latitude: float, range: float):
        response = []
        min_latitude = latitude - range
        min_longitude = longitude - range
        max_latitude = latitude + range
        max_longitude = longitude + range
        
        selector = {
            "selector": {
                "$and": [
                    {
                        "annotations": {
                            "$elemMatch": {
                                "latitude": {
                                    "$gte": min_latitude,
                                    "$lte": max_latitude
                                },
                                "longitude": {
                                    "$gte": min_longitude,
                                    "$lte": max_longitude
                                }
                            }
                        }
                    },
                    {
                        "type": entity_type
                    }
                ]
            },
            "limit": 100000,
        }
        result = self.query_data(selector)["result"]
        res = []
        for annotation in result:
            for anno in annotation["annotations"]:
                if anno["type"] == AnnotationType.Location:
                    response = {}
                    response["image_id"] = annotation["_id"]
                    response["image_path"] = annotation["image_path"]
                    response["extension"] = annotation["extension"]
                    response["filename"] = annotation["filename"]
                    response["uploaded_by"] = annotation["uploaded_by"]
                    response["uploaded_at"] = annotation["uploaded_at"]
                    response["latitude"] = anno["latitude"] if "latitude" in anno else 0
                    response["longitude"] = anno["longitude"] if "longitude" in anno else 0
                    response["locality"] = anno["locality"] if "locality" in anno else ""
                    response["city"] = anno["city"] if "city" in anno else ""
                    
                    if response not in res:
                        res.append(response)

        return res


    def search_by_tags(self, page: int, status: str, tags: List[str]) -> [str]:
        skip = (page - 1) * self.page_size
        url = (
            f"{self.base_url}/_design/query-metadata/_view/search-by-tag?"
            f'key=[ "{status}", "{tags[0]}" ]&limit={self.page_size}&skip={skip}&sorted=true&reduce=false'
        )
        response = self.client.request("GET", url, headers={}, data={})

        if response.status_code == 200:
            data = json.loads(response.text)["rows"]
            result = []
            for res in data:
                result.append(res["value"])
            return result
        return []

    def search_by_tags(self, page: int, status: str, tags: list, public_address: str) -> [str]:
        response = []
        selector = {
            "selector": {
                "$and": [
                    {
                        "annotations": {
                            "$elemMatch": {
                                "tags": {
                                    "$in": tags
                                },

                            }
                        }
                    },
                    {
                        "verified": {
                            "$not": {
                                "$elemMatch": {
                                    "by": public_address
                                }
                            }
                        }
                    }
                ]
            }
        }
        result = self.query_data(selector)["result"]
        res = []
        for annotation in result:
            for anno in annotation["annotations"]:
                if "public_address" in anno.keys():
                    if anno['public_address'] == annotation["uploaded_by"]:
                        if "tags" in anno.keys():
                            if set(anno["tags"]) & set(["knee", "shoulder"]):
                                response = {}
                                response["image_id"] = annotation["_id"]
                                response["image_path"] = annotation["image_path"]
                                if response not in res:
                                    res.append(response)

        # res = [{"image_id": r["_id"], "image_path": r["image_path"]} for r in result]
        return res

    def succes_rate(self, public_address: str) -> [str]:
        response = []
        selector = {
            "selector": {
                "annotations": {
                    "$elemMatch": {
                        "public_address": public_address
                    }
                }
            },
        }
        result = self.query_data(selector)["result"]

        total_count = len(result)
        correct_count = 0
        knee_classification_count = 0
        shoulder_classification_count = 0
        for annotation in result:
            response_dic = {}
            for anno in annotation["annotations"]:
                if "public_address" in anno.keys():
                    if anno['public_address'] == annotation["uploaded_by"]:
                        response_dic["uploaded_by"] = annotation["uploaded_by"]
                        if "tags" in anno.keys():
                            if set(anno["tags"]) & set(["knee", "shoulder"]):
                                response_dic["correct_tags"] = anno["tags"]
                    if anno["public_address"] == public_address:
                        if "tags" in anno.keys():
                            if set(anno["tags"]) & set(["knee", "shoulder"]):
                                if "knee" in anno["tags"]:
                                    knee_classification_count += 1
                                elif "shoulder" in anno["tags"]:
                                    shoulder_classification_count += 1
                                response_dic["tags"] = anno["tags"]
            if "correct_tags" in response_dic.keys() and "tags" in response_dic.keys():
                tags_set = set(response_dic["tags"])
                correct_tags_set = set(response_dic["correct_tags"])
                if tags_set & correct_tags_set:
                    correct_count += 1

        selector = {
            "selector": {
                "$and": [
                    {
                        "annotations": {
                            "$elemMatch": {
                                "tags": {
                                    "$eq": ['knee']
                                },
                                "public_address": public_address
                            }
                        }
                    }
                ]
            }
        }

        result = self.query_data(selector)["result"]
        knee_total_count = len(result)
        knee_correct_count = 0
        for annotation in result:
            response_dic = {}
            for anno in annotation["annotations"]:
                if "public_address" in anno.keys():
                    if anno['public_address'] == annotation["uploaded_by"]:
                        if "tags" in anno.keys():
                            if set(anno["tags"]) & set(["knee"]):
                                response_dic["correct_tags"] = anno["tags"]
                    if anno["public_address"] == public_address:
                        if "tags" in anno.keys():
                            if set(anno["tags"]) & set(["knee"]):
                                response_dic["tags"] = anno["tags"]
            if "correct_tags" in response_dic.keys() and "tags" in response_dic.keys():
                tags_set = set(response_dic["tags"])
                correct_tags_set = set(response_dic["correct_tags"])
                if tags_set & correct_tags_set:
                    knee_correct_count += 1

        selector = {
            "selector": {
                "$and": [
                    {
                        "annotations": {
                            "$elemMatch": {
                                "tags": {
                                    "$eq": ['shoulder']
                                },
                                "public_address": public_address
                            }
                        }
                    }
                ]
            }
        }

        result = self.query_data(selector)["result"]
        shoulder_total_count = len(result)
        shoulder_correct_count = 0
        for annotation in result:
            response_dic = {}
            for anno in annotation["annotations"]:
                if "public_address" in anno.keys():
                    if anno['public_address'] == annotation["uploaded_by"]:
                        if "tags" in anno.keys():
                            if set(anno["tags"]) & set(["shoulder"]):
                                response_dic["correct_tags"] = anno["tags"]
                    if anno["public_address"] == public_address:
                        if "tags" in anno.keys():
                            if set(anno["tags"]) & set(["shoulder"]):
                                response_dic["tags"] = anno["tags"]
            if "correct_tags" in response_dic.keys() and "tags" in response_dic.keys():
                tags_set = set(response_dic["tags"])
                correct_tags_set = set(response_dic["correct_tags"])
                if tags_set & correct_tags_set:
                    shoulder_correct_count += 1

        shoulder_success_rate = (
                                        shoulder_correct_count / shoulder_total_count) * 100 if shoulder_total_count != 0 else 0
        knee_success_rate = (knee_total_count / knee_total_count) * 100 if shoulder_total_count != 0 else 0
        success_rate = (correct_count / total_count) * 100 if total_count != 0 else 0
        classification_count = shoulder_classification_count + knee_classification_count
        shoulder_classification_percentage = (
                                                     shoulder_classification_count / classification_count) * 100 if classification_count != 0 else 0
        knee_classification_percentage = 100 - shoulder_classification_percentage if classification_count != 0 else 0
        return {
            "success_rate": success_rate,
            "shoulder_success_rate": shoulder_success_rate,
            "knee_success_rate": knee_success_rate,
            "classification_count": shoulder_classification_count + knee_classification_count,
            "shoulder_classification_percentage": shoulder_classification_percentage,
            "knee_classification_percentage": knee_classification_percentage
        }

    def image_result(self, image_id: str, option: str) -> [str]:
        response = []
        selector = {
            "selector": {
                "_id": {
                    "$eq": image_id
                }
            },
        }
        result = self.query_data(selector)["result"]
        for annotation in result:
            response_dic = {}
            for anno in annotation["annotations"]:
                if "public_address" in anno.keys():
                    if anno['public_address'] == annotation["uploaded_by"]:
                        response_dic["uploaded_by"] = annotation["uploaded_by"]
                        if "tags" in anno.keys():
                            if set(anno["tags"]) & set(["knee", "shoulder"]):
                                if set(anno["tags"]) & set(option):
                                    return True
        return False

    def global_succes_rate(self) -> [str]:
        response = []
        selector = {
            "selector": {
                "annotations": {
                    "$elemMatch": {
                        "tags": {
                            "$in": ["knee", "shoulder"]
                        }
                    }
                }
            }
        }
        result = self.query_data(selector)["result"]
        total_count = len(result)
        correct_count = 0
        knee_upload_count = 0
        shoulder_upload_count = 0
        knee_classification_count = 0
        shoulder_classification_count = 0
        for annotation in result:
            response_dic = {}
            for anno in annotation["annotations"]:
                if "public_address" in anno.keys():
                    if anno['public_address'] == annotation["uploaded_by"]:
                        response_dic["uploaded_by"] = annotation["uploaded_by"]
                        if "tags" in anno.keys():
                            if set(anno["tags"]) & set(["knee", "shoulder"]):
                                if "knee" in anno["tags"]:
                                    knee_upload_count += 1
                                elif "shoulder" in anno["tags"]:
                                    shoulder_upload_count += 1
                                response_dic["correct_tags"] = anno["tags"]
                    if "tags" in anno.keys():
                        if set(anno["tags"]) & set(["knee", "shoulder"]):
                            if "knee" in anno["tags"]:
                                knee_classification_count += 1
                            elif "shoulder" in anno["tags"]:
                                shoulder_classification_count += 1
                            response_dic["tags"] = anno["tags"]
            if "correct_tags" in response_dic.keys() and "tags" in response_dic.keys():
                tags_set = set(response_dic["tags"])
                correct_tags_set = set(response_dic["correct_tags"])
                if tags_set & correct_tags_set:
                    correct_count += 1
        success_rate = (correct_count / total_count) * 100 if total_count != 0 else 0
        classification_count = shoulder_classification_count + knee_classification_count
        shoulder_classification_percentage = (
                                                     shoulder_classification_count / classification_count) * 100 if classification_count != 0 else 0
        knee_classification_percentage = 100 - shoulder_classification_percentage if classification_count != 0 else 0

        upload_count = shoulder_upload_count + knee_upload_count
        shoulder_upload_percentage = (shoulder_upload_count / upload_count) * 100 if upload_count != 0 else 0
        knee_upload_percentage = 100 - shoulder_upload_percentage if upload_count != 0 else 0
        return {
            "success_rate": success_rate,
            "classification_count": shoulder_classification_count + knee_classification_count,
            "shoulder_classification_percentage": shoulder_classification_percentage,
            "knee_classification_percentage": knee_classification_percentage,
            "upload_count": upload_count,
            "shoulder_upload_percentage": shoulder_upload_percentage,
            "knee_upload_percentage": knee_upload_percentage
        }

    def search_entities_by_tags(self, entity_type: EntityType, annotation_type: AnnotationType,
                                page: int, fields: List[str], query_type: str, tags: List[str], page_size: int) -> any:

        query = {"selector": {"type": entity_type, query_type: []}, 'fields': fields,
                 "limit": page_size,
                 "skip": (page - 1) * page_size}

        for tag in tags:
            query["selector"][query_type].append({
                "annotations": {"$elemMatch": {
                    "type": annotation_type,
                    "tags": {
                        "$elemMatch": {
                            "$eq": tag
                        }
                    }
                }}
            })
        result = self.query_all(query)
        total_count = len(result)

        # result = self.query_data(query)["result"]
        end = min(len(result), page * page_size)
        entities = result[(page - 1) * page_size: end]
        # TODO: Fix below statement. Return list of object instead of list of str in result
        entities = [r['_id'] for r in entities]
        return {"result": entities, "total_count": total_count, "page": page, "page_size": page_size}

    def get_tags_by_image_status(self, status: str) -> [str]:

        url = (
            f"{self.base_url}/_design/query-metadata/_view/search-by-tag?sorted=true&group_level="
            f'2&start_key=["{status}"]&end_key=["{status}",{{}}]'
        )
        response = self.client.request("GET", url, headers={}, data={})

        if response.status_code != 200:
            return []

        rows = json.loads(response.text)["rows"]
        result = []
        for row in rows:
            result.append(row["key"][1])

        return result

    def get_tags_by_image_ids(self, image_ids: [str]) -> [str]:

        url = (
            f"{self.base_url}/_design/query-metadata/_view/votes-for-tags?sorted=true"
            f"&keys={json.dumps(image_ids)}"
        )
        response = self.client.request("GET", url, headers={}, data={})

        if response.status_code != 200:
            return []

        rows = [
            {"image_id": row["key"], "value": row["value"]}
            for row in json.loads(response.text)["rows"]
        ]
        return rows
    
    def init_annotation(
            self, entity_id: str
    ) -> bool:
        document = self.get_doc_by_id(entity_id)
        document["annotations"] = []
        self.update_doc(entity_id, document)
        return True

    def add_annotation_to_image(
            self, image_id: str, annotations: [BaseAnnotation]
    ) -> bool:

        document = self.get_doc_by_id(image_id)
        if document.get("annotations") is None:
            document["annotations"] = []

        for annotation in annotations:
            document["annotations"].append(annotation.get_data_for_db())

        self.update_doc(image_id, document)

        return True

    def add_annotation_to_child_entity(
            self, child_entity_id: str, annotations: [BaseAnnotation]
    ) -> bool:

        document = self.get_doc_by_id(child_entity_id)
        if document.get("parent", False) is True:
            raise DBResultError(self.db_name, f"Not a child doc [{child_entity_id}]")

        if document.get("annotations") is None:
            document["annotations"] = []

        for annotation in annotations:
            document["annotations"].append(annotation.get_data_for_db())

        self.update_doc(child_entity_id, document)

        return True

    def get_annotations_for_images(
            self, image_ids: [str], annotation: AnnotationType
    ) -> object:

        keys = [f"[\"{image_id}\", \"{annotation.name}\"]" for image_id in image_ids]
        keys = "[" + ",".join(keys) + "]"
        url = f"{self.base_url}/_design/query-metadata/_view/annotations?keys={keys}"
        response = self.client.request("GET", url, headers={}, data={})

        if response.status_code != 200:
            return []

        rows = json.loads(response.text)["rows"]

        result = [{"image_id": row["id"], "value": row["value"]} for row in rows]

        return result

    def get_image_counts_for_tags(self, tag_names: str) -> object:
        filter_param = f'&keys={json.dumps(tag_names)}' if tag_names else ''
        url = f'{self.base_url}/_design/stats/_view/images-per-tag?group=true' + filter_param

        response = self.client.request("GET", url, headers={}, data={})

        if not response.ok:
            raise DBResultError(self.db_name, response.text)

        rows = response.json()["rows"]

        result = [{"tag": row["key"][-1], "count": row["value"]} for row in rows]

        return result

    def get_tag_stats_by_bounty(self, bounty_name: str):

        url = f"{self.base_url}/_design/stats/_view/tags-by-bounty?group_level=2&start_key=[\"{bounty_name}\"]" \
              f"&end_key=[\"{bounty_name}\",{{}}]"

        response = self.client.request("GET", url, headers={}, data={})

        if response.status_code != 200:
            raise DBResultError(self.db_name, response.text)

        rows = json.loads(response.text)["rows"]

        data = [{'tag': row['key'][1], 'count': row['value']} for row in rows]
        return data

    def get_user_stats_count(self, public_address: str, entity_type: EntityType, start_date: datetime,
                             end_date: datetime) -> dict:

        result = self.get_user_stats(entity_type.value, public_address, start_date, end_date)
        upload_count = sum([x['value'] for x in result['uploads']])
        tag_annotations_count = sum([x['value'] for x in result['tag_annotations']])
        text_annotations_count = sum([x['value'] for x in result['text_annotations']])
        verifications_count = sum([x['value'] for x in result['verifications']])

        return {
            'uploads': upload_count,
            'tag_annotations': tag_annotations_count,
            'text_annotations': text_annotations_count,
            'verifications': verifications_count
        }

    def get_docs_type(self, doc_ids: list) -> list:
        query = {
            "selector": {
                "_id": {"$in": doc_ids}
            },
            "fields": ["type"]
        }
        result = self.query_all(query)
        entity_types = [r['type'] for r in result]
        return entity_types

    def add_new_image_entity(self, doc_id: str, public_address: str, filename: str, destination_path: str, w: int,
                             h: int, bounty_name: list, storage: str = None) -> str:
        data_to_save = dict({})
        data_to_save["filename"] = filename
        data_to_save["uploaded_by"] = public_address
        data_to_save["status"] = ImageStatus.VERIFIABLE.name
        data_to_save["hash"] = doc_id
        data_to_save["type"] = "image"
        data_to_save["extension"] = filename.split(".")[-1]
        data_to_save["status_description"] = ImageStatus.VERIFIABLE.name
        data_to_save["uploaded_at"] = datetime.timestamp(datetime.utcnow())
        data_to_save["dimensions"] = [w, h]
        data_to_save["image_path"] = destination_path
        data_to_save["verified"] = []
        data_to_save["annotations"] = []
        data_to_save["bounty"] = bounty_name
        data_to_save["storage"] = storage

        # Save metadata
        return self.save(doc_id, data_to_save)["id"]

    def add_new_video_entity(self, doc_id: str, public_address: str, filename: str, destination_path: str,
                             bounty_name: list, storage: str = None) -> str:
        data_to_save = dict({})
        data_to_save["filename"] = filename
        data_to_save["uploaded_by"] = public_address
        data_to_save["hash"] = doc_id
        data_to_save["type"] = "video"
        data_to_save["extension"] = filename.split(".")[-1]
        data_to_save["uploaded_at"] = datetime.timestamp(datetime.utcnow())
        data_to_save["video_path"] = destination_path
        data_to_save["verified"] = []
        data_to_save["annotations"] = []
        data_to_save["bounty"] = bounty_name
        data_to_save["status"] = ImageStatus.VERIFIABLE.name
        data_to_save["storage"] = storage

        # Save metadata
        return self.save(doc_id, data_to_save)["id"]

    def add_new_media_entity(self,
                             doc_id: str,
                             type: str,
                             public_address: str,
                             filename: str,
                             destination_path: str,
                             bounty_name: list,
                             w: int = 0, h: int = 0,
                             source: str = None,
                             storage: str = None,
                             qrcode_id: str = None) -> str:
        data_to_save = dict({})
        data_to_save["filename"] = filename
        data_to_save["uploaded_by"] = public_address
        data_to_save["hash"] = doc_id
        data_to_save["type"] = type
        data_to_save["extension"] = os.path.splitext(filename)[-1].lower().split('.')[-1]
        data_to_save["uploaded_at"] = datetime.timestamp(datetime.utcnow())
        data_to_save["verified"] = []
        data_to_save["annotations"] = []
        data_to_save["bounty"] = bounty_name
        data_to_save["status"] = ImageStatus.VERIFIABLE.name
        data_to_save["source"] = source
        data_to_save["available_for_annotation"] = True
        data_to_save["available_for_verification"] = True
        data_to_save["available_for_download"] = True
        data_to_save["storage"] = storage
        data_to_save["qrcode_id"] = qrcode_id

        if type == "image":
            data_to_save["status_description"] = ImageStatus.VERIFIABLE.name
            data_to_save["dimensions"] = [w, h]
            data_to_save["image_path"] = destination_path
            
            if source != None and source == Source.recyclium:
                data_to_save["qr_code"] = qr_code
                
        elif type == "video":
            data_to_save["video_path"] = destination_path
        else:
            data_to_save["audio_path"] = destination_path

        # Save metadata
        return self.save(doc_id, data_to_save)["id"]

    def search_entity_ids_by_annotations(self, entity_type: EntityType, annotation_type: AnnotationType) -> List[str]:
        query = {
            "selector": {
                "_id": {"$gt": None}
            },
            "fields": ["_id"]
        }

        self.query_all(query)

    def get_entity_count(self, source: str, group_level: int = 2):

        source = f"\"{source}\"" if source else 'null'

        url = f"{self.base_url}/_design/stats/_view/entity_count?group_level={group_level}&" \
              f"start_key=[{source}]" \
              f"&end_key=[{source},{{}}]"

        response = self.client.request("GET", url, headers={}, data={})

        if response.status_code != 200:
            raise DBResultError(self.db_name, response.text)

        return json.loads(response.text)

    def get_all_entity_uploads(self, source: str, start_time: datetime, end_time: datetime):

        source = f"\"{source}\"" if source else 'null'
        start_key = f"{source},{start_time.year},{start_time.month},{start_time.day},{start_time.hour}"
        end_key = f"{source},{end_time.year},{end_time.month},{end_time.day},{end_time.hour}"
        url = f"{self.base_url}/_design/stats/_view/all-entities?" \
              f"start_key=[{start_key}]" \
              f"&end_key=[{end_key}]"

        response = self.client.request("GET", url, headers={}, data={})

        if response.status_code != 200:
            raise DBResultError(self.db_name, response.text)

        return json.loads(response.text)

    def get_user_success_rate(self, public_address: str):
        url = f"{self.base_url}/_design/stats/_view/success-rate?" \
              f"key=\"{public_address}\""
        response = self.client.request("GET", url, headers={}, data={})

        if response.status_code != 200:
            raise DBResultError(self.db_name, response.text)

        return json.loads(response.text)

    def get_tag_counts(self, tags: List[str]) -> object:
        keys = [f"\"{key}\"" for key in tags]
        keys = "[" + ",".join(keys) + "]"
        url = f"{self.base_url}/_design/stats/_view/true-tags?group=true&keys={keys}"

        response = self.client.request("GET", url, headers={}, data={})

        if response.status_code != 200:
            raise DBResultError(self.db_name, response.text)

        return json.loads(response.text)

    def add_new_json_entity(self, doc_id: str, public_address: str, raw: dict,
                            json_entity_type: EntitySubType, source: Source = Source.wedatanation,
                            annotations_required: List[AnnotationType] = (), public=None,
                            rewardable: bool = False) -> str:
        data_to_save = dict({})
        data_to_save["uploaded_by"] = public_address
        data_to_save["doc_id"] = doc_id
        data_to_save["type"] = EntityType.json
        data_to_save["uploaded_at"] = datetime.timestamp(datetime.utcnow())
        data_to_save["created_at"] = datetime.timestamp(datetime.utcnow())
        data_to_save["json_entity_type"] = json_entity_type
        # json_entity_type = entity_sub_type
        data_to_save["entity_sub_type"] = json_entity_type
        data_to_save["raw"] = raw
        data_to_save["parent"] = True
        data_to_save["status"] = None
        data_to_save["child_docs"] = []
        data_to_save["monetization_status"] = MonetizationStatus.enabled
        data_to_save["source"] = source
        data_to_save["annotations_required"] = annotations_required
        data_to_save["available_for_annotation"] = True if len(annotations_required) else False
        data_to_save["public"] = public
        data_to_save["reward_information"] = {
            "reward_status": EntityRewardStatus.unpaid,
            "can_be_rewarded": rewardable
        }
        data_to_save["user_submissions"] = {}

        for annotation_type in annotations_required:
            data_to_save["user_submissions"][annotation_type] = []

        self.save(doc_id, data_to_save)
        return doc_id

    def add_new_child_entity(self, doc_id: str, public_address: str, parent_doc_id: str, raw: dict,
                             json_entity_type: EntitySubType,
                             chunk: int = 0, source: Source = Source.wedatanation) -> str:
        data_to_save = dict({})
        data_to_save["uploaded_by"] = public_address
        data_to_save["doc_id"] = doc_id
        data_to_save["type"] = EntityType.json
        data_to_save["uploaded_at"] = datetime.timestamp(datetime.utcnow())
        data_to_save["created_at"] = datetime.timestamp(datetime.utcnow())
        data_to_save["json_entity_type"] = json_entity_type
        data_to_save["raw"] = raw
        data_to_save["parent"] = False
        data_to_save["chunk"] = chunk
        data_to_save["parent_doc_id"] = parent_doc_id
        data_to_save["source"] = source
        data_to_save["annotations"] = []
        self.save(doc_id, data_to_save)
        return doc_id

    def get_ncight_classification_stats(self) -> Any:

        url = f"{self.base_url}/_design/ncight/_view/classification-stats?reduce=true&group_level=1"
        payload = {}
        headers = {}

        response = self.client.request("GET", url, headers=headers, data=payload)

        if response.status_code != 200:
            raise DBResultError(self.db_name, response.text)

        return json.loads(response.text)

    def get_child_web3_docs(self, user_address: str, wallet_address: str, network: Network) -> List[object]:
        query = {
            'selector': {
                'json_entity_type': EntitySubType.web3,
                'type': 'json',
                'parent': True,
                'uploaded_by': user_address,
                "raw": {
                    "wallet_address": wallet_address,
                    "network": network
                }
            },
            'fields': ['child_docs']
        }
        doc_ids = self.query_all(query)[0]['child_docs']
        result = []
        for doc_id in doc_ids:
            result.append(self.get_doc_by_id(doc_id))
        return result

    def get_child_doc_id(self, parent_doc_id: str):
        query = {
            'selector': {
                'parent': True,
                '_id': parent_doc_id,
            },
            'fields': ['child_docs']
        }
        doc_ids = self.query_all(query)[0]['child_docs']
        return doc_ids
    
    def get_amount_collector_by_mission_id(self, mission_id: str):
        selector = {
            "selector": {"_id": {"$gt": None}, "mission_id": mission_id},
            'fields': ["_id", "uploaded_by"],
        }
        return self.query_data(selector)["result"]

    def get_collectors_by_mission_id(self, mission_id: str):
        selector = {
            "selector": {"_id": {"$gt": None}, "mission_id": mission_id},
            'fields': ["uploaded_by"],
        }
        return self.query_data(selector)["result"]

    def get_metadata_by_bounty_id(self, bounty_id: str):
        selector = {
            "selector": {"_id": {"$gt": None}, "bounty_id": bounty_id},
            'fields': ["_id"],
        }
        return self.query_data(selector)["result"]

    def get_metadata_by_qrcode_id(self, qrcode_id: str):
        selector = {
            "selector": {"_id": {"$gt": None}, "qrcode_id": qrcode_id},
            'fields': ["_id"],
        }
        return self.query_data(selector)["result"]

    def get_image_by_qrcode(self, qrcode: list):
        selector = {
            "selector": {"_id": {"$gt": None}, "qr_code": qrcode},
            'fields': ["_id", "qr_code", "bounty_id"],
        }
        return self.query_data(selector)["result"]

    
    def update_mission_bounty_id(self, doc_id, bounty_id, mission_id):
        document = self.get_doc_by_id(doc_id)
        document["bounty_id"] = bounty_id
        document["mission_id"] = mission_id
        self.update_doc(doc_id, document)

image_metadata_dao = ImageMetadataDao()
image_metadata_dao.set_config(
    config["couchdb"]["user"],
    config["couchdb"]["password"],
    config["couchdb"]["db_host"],
    config["couchdb"]["metadata_db"],
)
