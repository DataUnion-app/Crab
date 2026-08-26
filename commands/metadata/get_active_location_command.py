from dao.metadata_dao import image_metadata_dao
from commands.base_command import BaseCommand

class GetActiveLocationCommand(BaseCommand):

    def __init__(self):
        super().__init__()
        self.image_metadata_dao = image_metadata_dao

    def execute(self):
        self.successful = True
        metadata = image_metadata_dao.query_view_by_key_range("stats", "latitude_count", None, None, 3)['rows']
        metadata.sort(key=lambda x: x["value"], reverse=True)
        metadata = list(map((lambda x: {**x,"bounty_id" : x["key"][0]}), metadata))
        metadata = list({i['bounty_id']:i for i in reversed(metadata)}.values())
        metadata.sort(key=lambda x: x["value"], reverse=True)
        return metadata[0:10]