from dao.base_dao import BaseDao
from config import config
from models.taxonomy.TaxonomyImageStatus import TaxonomyImageStatus
from models.taxonomy.TaxonomyTypes import TaxonomyTypes
from datetime import datetime
import json


class TaxonomyDao(BaseDao):
    def __init__(self):
        super().__init__()

    def get_verifiable_images(self, public_address):
        selector = {
            "selector": {
                "status": TaxonomyImageStatus.VERIFIABLE.name,
                "type": TaxonomyTypes.CROP.name,
                "$not": {
                    "verified": {
                        "$elemMatch": {"public_address": {"$eq": public_address}}
                    }
                },
            },
            "sort": [{"created_at": "desc"}],
            "fields": ["_id", "label"],
            "limit": self.page_size,
            "skip": 0,
        }

        result = self.query_data(selector)["result"]
        res = [{"image_id": r["_id"], "label": r["label"]} for r in result]
        return res

    def get_user_swipe_stats(
        self, public_address: str, start_date: datetime, end_date: datetime
    ):
        start_key = f'["{public_address}",{start_date.year},{start_date.month},{start_date.day}]'
        end_key = (
            f'["{public_address}",{end_date.year},{end_date.month},{end_date.day},{{}}]'
        )

        query_url = f"/_design/stats/_view/user-stats-view?start_key={start_key}&end_key={end_key}&group_level=5"

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
            response_type = row["key"][4]

            if response_type not in result:
                result[response_type] = []

            value = row["value"]
            result[response_type].append(
                {
                    "date": datetime.strptime(
                        f"{date}-{month}-{year}", "%d-%m-%Y"
                    ).strftime("%d-%m-%Y"),
                    "value": value,
                }
            )

        return result

    def get_overall_swipe_stats(self, start_date: datetime, end_date: datetime):
        start_key = f"[{start_date.year},{start_date.month},{start_date.day}]"
        end_key = f"[{end_date.year},{end_date.month},{end_date.day},{{}}]"

        query_url = f"/_design/stats/_view/overall-stats-view?start_key={start_key}&end_key={end_key}&group_level=4"

        url = f"{self.base_url}{query_url}"
        headers = {"Content-Type": "application/json"}
        payload = {}
        response = self.client.request("GET", url, headers=headers, data=payload)

        data = json.loads(response.text)
        result = {}
        for row in data["rows"]:
            year = row["key"][0]
            month = row["key"][1]
            date = row["key"][2]
            response_type = row["key"][3]

            if response_type not in result:
                result[response_type] = []

            value = row["value"]
            result[response_type].append(
                {
                    "date": datetime.strptime(
                        f"{date}-{month}-{year}", "%d-%m-%Y"
                    ).strftime("%d-%m-%Y"),
                    "value": value,
                }
            )

        return result


taxonomy_dao = TaxonomyDao()
taxonomy_dao.set_config(
    config["couchdb"]["user"],
    config["couchdb"]["password"],
    config["couchdb"]["db_host"],
    config["couchdb"]["taxonomy_db"],
)
