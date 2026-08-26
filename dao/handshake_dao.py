import json


from config import config
from datetime import datetime
from dao.base_dao import BaseDao, DBResultError


class HandshakeDao(BaseDao):
    def __init__(self):
        super(HandshakeDao).__init__()
        self.id_prefix = 'handshake'

    def add_new_handshake(self, location: str, initiated_by: str, completed_by: str, source: str):
        doc_id = self.generate_new_doc_id()
        self.save(
            doc_id,
            {
                "created_time": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.%f%Z"),
                "location": location,
                "initiated_by": initiated_by,
                "completed_by": completed_by,
                "source": source
            },
        )
        return doc_id

    def get_all_handshakes(self):
        result = self.get_all()['result']

        res = [
            {
                "handshake_id": r["_id"],
                "created_time": r["created_time"],
                "location": r["location"],
                "initiated_by": r["initiated_by"],
                "completed_by": r["completed_by"],
                "source": r.get("source")
            }
            for r in result
        ]
        return res

    def get_hourly_count(self, source: str):
        source = f"\"{source}\"" if source else 'null'

        url = f"{self.base_url}/_design/stats/_view/hourly-count?group_level=5&" \
              f"start_key=[{source}]" \
              f"&end_key=[{source},{{}}]"

        response = self.client.request("GET", url, headers={}, data={})

        if response.status_code != 200:
            raise DBResultError(self.db_name, response.text)

        return json.loads(response.text)

    def get_by_time(self, source: str, start_time: datetime, end_time: datetime):

        source = f"\"{source}\"" if source else 'null'
        start_key = f"{source},{start_time.year},{start_time.month},{start_time.day},{start_time.hour}"
        end_key = f"{source},{end_time.year},{end_time.month},{end_time.day},{end_time.hour}"
        url = f"{self.base_url}/_design/stats/_view/all-handshakes?" \
              f"start_key=[{start_key}]" \
              f"&end_key=[{end_key}]"

        response = self.client.request("GET", url, headers={}, data={})

        if response.status_code != 200:
            raise DBResultError(self.db_name, response.text)

        return json.loads(response.text)


handshake_dao = HandshakeDao()
handshake_dao.set_config(
    config["couchdb"]["user"],
    config["couchdb"]["password"],
    config["couchdb"]["db_host"],
    config["couchdb"]["handshake_db"],
)
