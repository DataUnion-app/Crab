from dao.image_metadata_dao import image_metadata_dao
from commands.base_command import BaseCommand
from datetime import datetime
import pandas as pd
import json


class MyStatsCommand(BaseCommand):

    def __init__(self):
        self.imageMetadataDao = image_metadata_dao

    def execute(self):
        page_size = 100

        selector = {
            "selector": {
                "_id": {
                    "$gt": None
                },
                "uploaded_by": self.input['public_address'],
                "type": "image",
                "uploaded_at": {
                    "$gte": self.input['start_time'],
                    "$lt": self.input['end_time']
                }
            },
            "fields": [
                "uploaded_at"
            ],
            "limit": page_size,
            "skip": 0,
            "sort": [
                "uploaded_at"
            ]
        }

        all_data = []

        while True:
            result = self.imageMetadataDao.query_data(selector)["result"]
            if result is not None:
                all_data = all_data + result
            selector["skip"] = selector["skip"] + page_size
            if len(result) < page_size:
                break

        data = {
            "uploaded_at": [datetime.fromtimestamp(row['uploaded_at']).strftime('%Y-%m-%d %H:%M:%S') for row in
                            all_data]}
        d = pd.DataFrame.from_dict(data, orient='columns')
        d['uploaded_at'] = pd.to_datetime(d['uploaded_at'])
        d['idx'] = d['uploaded_at']
        d = d.set_index('idx')

        # Group by hours. Default = 24
        group_by = str(self.input.get('group_by', 24)) + 'H'

        groups = d.groupby(pd.Grouper(freq=group_by)).count().reset_index()
        groups = groups.rename(columns={"idx": "time", "uploaded_at": "num_images"})
        result = {"status": "success", "result": json.loads(groups.to_json(orient='records'))}
        return result

    @property
    def is_valid(self):
        pass
