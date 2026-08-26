from datetime import datetime

from commands.base_command import BaseCommand
from dao.metadata_dao import image_metadata_dao
from dao.users_dao import user_dao


class GetEntityCountBySource(BaseCommand):

    def __init__(self, source: str):
        super().__init__()
        self.source = source

    def execute(self):
        result = image_metadata_dao.get_entity_count(self.source)['rows']
        data = [{'type': row['key'][1], 'count': row['value']} for row in result]
        self.successful = True
        return data


class GetEntityUploadsPerHour(BaseCommand):
    def __init__(self, source: str):
        super().__init__()
        self.source = source

    def execute(self):
        result = image_metadata_dao.get_entity_count(source=self.source, group_level=6)['rows']
        data = [{'type': row['key'][1],
                 'date': f"{row['key'][2]}-{row['key'][3]}-{row['key'][4]}T{row['key'][5]}:00:00.000000",
                 'count': row['value']} for row in result]
        self.successful = True
        return data


class GetEntityAllEntities(BaseCommand):
    def __init__(self, source: str, start_time: datetime, end_time: datetime):
        super().__init__()
        self.source = source
        self.start_time = start_time
        self.end_time = end_time

    def execute(self):
        result = image_metadata_dao.get_all_entity_uploads(self.source, self.start_time, self.end_time)['rows']
        data = []
        for row in result:
            data.append({'type': row['value']['type'],
                         'date': f"{row['key'][3]}-{row['key'][2]}-{row['key'][1]}"
                                 f" {row['key'][4]}:{row['key'][5]}:{row['key'][6]}",
                         'location': row['value']["location"]})
        self.successful = True
        return data


class GetClassificationAccuracy(BaseCommand):

    def __init__(self):
        super(GetClassificationAccuracy, self).__init__()

    def execute(self):
        rows = image_metadata_dao.get_ncight_classification_stats()["rows"]
        public_addresses = [f"\"{r['key']}\"" for r in rows]
        address_name_mapping = user_dao.query_view_by_keys(design_doc="user-info", view_name="address-name-mapping",
                                                           keys=public_addresses)['rows']
        referrals = user_dao.query_view_by_keys(design_doc="counts", view_name="referrals",
                                                           keys=public_addresses)['rows']
        result = []
        for r in rows:
            user_name = [x["value"] for x in address_name_mapping if x["key"] == r["key"]]
            referral_count = [x["value"] for x in referrals if x["key"] == r["key"]]

            user_name = user_name[0] if len(user_name) == 1 else None
            referral_count = referral_count[0] if len(referral_count) == 1 else None

            result_row = {**r["value"], 'public_address': r["key"],
                          "user_name": user_name, "referrals": referral_count}
            result.append(result_row)
        result.sort(key=lambda x: (x["user_name"] is None, x["user_name"]))
        self.successful = True
        return result
