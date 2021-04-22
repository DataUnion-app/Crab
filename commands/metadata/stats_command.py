from dao.image_metadata_dao import image_metadata_dao
from commands.base_command import BaseCommand
from datetime import datetime
import pandas as pd
from models.ImageStatus import ImageStatus


class StatsCommand(BaseCommand):

    def __init__(self):
        super().__init__()
        self.imageMetadataDao = image_metadata_dao()

    def execute(self):
        is_valid = self.validate_input()

        if is_valid is False:
            self.successful = False
            return

        page_size = 100

        selector = {
            "selector": {
                "_id": {
                    "$gt": None
                },
                "type": "image",
                "status": {
                    "$in": [ImageStatus.VERIFIABLE.name, ImageStatus.VERIFIED.name]
                },
                "uploaded_at": {
                    "$gte": self.input['start_time'],
                    "$lt": self.input['end_time']
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

        # Interval in hours
        interval = str(self.input['interval']) + 'H'

        groups = d.groupby(pd.Grouper(key='time', freq=interval))
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

    def validate_input(self):
        if self.input is None:
            self.messages.append("Empty input")
            return

        if self.input.get('start_time') is None:
            self.messages.append("Missing start_time")
            return False

        if self.input.get('end_time') is None:
            self.messages.append("Missing end_time")
            return False

        if self.input.get('interval') is None:
            self.messages.append("Missing interval")
            return False
