import datetime
from enum import Enum
from typing import List

from config import config
from dao.base_dao import BaseDao
from utils.get_random_string import get_random_string


class OtherDocumentType(str, Enum):
    notifications = "notifications"


class NotificationType(str, Enum):
    referral_used = "referral_used"
    rank_updated = "rank_updated"

class OthersDao(BaseDao):

    def get_notifications_for_user(self, public_address: str) -> List[object]:
        doc_id = f"notifications-{public_address}"

        query = {
            "selector": {
                "_id": doc_id
            },
            "fields": ["pending_notifications"],
            "limit": 1
        }
        result = self.query_all(query)
        if len(result) == 0:
            return []

        return result[0]["pending_notifications"]

    def generate_notification_for_user(self, public_address: str, notification_type: NotificationType, data: dict):
        doc_id = f"notifications-{public_address}"
        exists, doc = self.get_if_exists(doc_id)

        notification_info = {
            "type": notification_type,
            "data": data,
            "id": "notification-" + get_random_string(10),
            "created_at": datetime.datetime.utcnow().isoformat()
        }

        if not exists:
            self.save(doc_id, {
                "pending_notifications": [notification_info],
                "delivered_notifications": []
            })
        else:
            doc["pending_notifications"].append(notification_info)
            self.update_doc(doc_id, doc)

    def generate_or_replace_notification_for_user_by_type(self, public_address: str,
                                                          notification_type: NotificationType, data: dict):
        doc_id = f"notifications-{public_address}"
        exists, doc = self.get_if_exists(doc_id)

        notification_info = {
            "type": notification_type,
            "data": data,
            "id": "notification-" + get_random_string(10),
            "created_at": datetime.datetime.utcnow().isoformat()
        }

        if not exists:
            self.save(doc_id, {
                "pending_notifications": [notification_info],
                "delivered_notifications": []
            })
        else:
            new_pending_notifications = [p for p in doc["pending_notifications"] if p["type"] != notification_type]
            doc["pending_notifications"] = new_pending_notifications
            doc["pending_notifications"].append(notification_info)
            self.update_doc(doc_id, doc)

    def mark_notifications_as_read(self, public_address: str, notification_ids: List[str]):

        if len(notification_ids) == 0:
            return

        doc_id = f"notifications-{public_address}"
        exists, doc = self.get_if_exists(doc_id)

        pending_notifications = doc["pending_notifications"]
        new_pending_notifications = [p for p in pending_notifications if p["id"] not in notification_ids]
        mark_as_delivered = [p for p in pending_notifications if p["id"] in notification_ids]

        read_time = datetime.datetime.utcnow().isoformat()
        for m in mark_as_delivered:
            m.update({"delivered_at": read_time})

        doc["delivered_notifications"] = doc["delivered_notifications"] + mark_as_delivered
        doc["pending_notifications"] = new_pending_notifications
        self.update_doc(doc_id, doc)

others_db = OthersDao()
others_db.set_config(
    config["couchdb"]["user"],
    config["couchdb"]["password"],
    config["couchdb"]["db_host"],
    config["couchdb"]["others_db"],
)
