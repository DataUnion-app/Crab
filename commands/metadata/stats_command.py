from dao.ImageMetadataDao import ImageMetadataDao
from commands.base_command import BaseCommand
from config import config
from datetime import datetime
import pandas as pd
from models.ImageStatus import ImageStatus


class StatsCommand(BaseCommand):

    def __init__(self):
        user = config['couchdb']['user']
        password = config['couchdb']['password']
        db_host = config['couchdb']['db_host']
        metadata_db = config['couchdb']['metadata_db']
        self.imageMetadataDao = ImageMetadataDao()
        self.imageMetadataDao.set_config(user, password, db_host, metadata_db)

    def execute(self):
        page_size = 100

        selector = {
            "selector": {
                "_id": {
                    "$gt": None
                },
                "type": "image",
                "status": {
                    "$in": [ImageStatus.AVAILABLE_FOR_TAGGING.name, ImageStatus.VERIFIED.name]
                }
            },
            "fields": [
                "uploaded_at",
                "tag_data",
                "_id"
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

        data = dict({})

        for row in all_data:
            data[row['_id']] = {'time': datetime.fromtimestamp(row['uploaded_at']).strftime('%Y-%m-%d %H:%M:%S'),
                                'tags': []}
            tags_set = set()
            tag_data = row.get('tag_data')
            if tag_data:
                for tags in tag_data:
                    for tag in tags['tags']:
                        tags_set.add(tag)
                data[row['_id']]['tags'] = tags_set
        d = pd.DataFrame.from_dict(data, orient='index')
        d['time'] = pd.to_datetime(d['time'])
        groups = d.groupby(pd.Grouper(key='time', freq='D'))
        total_summary = []
        for key, group in groups:
            summary = dict({})
            summary['time'] = key.timestamp()
            summary['num_images'] = 0
            summary['tags'] = []
            for row_index, row in group.iterrows():
                summary['num_images'] = summary['num_images'] + 1
                for tag in row['tags']:
                    present = False
                    for index, s in enumerate(summary['tags']):
                        if s.get('name') == tag:
                            present = True
                            summary['tags'][index]['value'] = summary['tags'][index]['value'] + 1
                    if not present:
                        value = {"name": tag, "value": 1}
                        summary['tags'].append(value)
            total_summary.append(summary)

        result = dict({
            "initial_images": len(all_data),
            "data": total_summary
        })

        self.successful = True
        result = {"status": "success", "result": result}
        return result

    @property
    def is_valid(self):
        pass
