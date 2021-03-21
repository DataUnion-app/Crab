from dao.image_metadata_dao import ImageMetadataDao
from commands.base_command import BaseCommand
from config import config


class QueryMetadataCommand(BaseCommand):

    def __init__(self):
        super().__init__()
        user = config['couchdb']['user']
        password = config['couchdb']['password']
        db_host = config['couchdb']['db_host']
        metadata_db = config['couchdb']['metadata_db']
        self.imageMetadataDao = ImageMetadataDao()
        self.imageMetadataDao.set_config(user, password, db_host, metadata_db)

    def execute(self):

        is_valid = self.validate_input()

        if is_valid is False:
            self.successful = False
            return

        result = self.imageMetadataDao.query_metadata(self.input['status'], self.input['page'], self.input['fields'])
        self.successful = True
        return result

    def validate_input(self):
        if self.input is None:
            self.messages.append("Empty input")
            return False

        if self.input.get('status') is None:
            self.messages.append("Missing status")
            return False

        if self.input.get('page') is None:
            self.messages.append("Missing page")
            return False
        elif not isinstance(self.input.get('page'), int):
            self.messages.append("Page is not a number")
            return False

        if self.input.get('fields') is None:
            self.messages.append("Missing fields")
            return False
        elif not isinstance(self.input.get('fields'), list):
            self.messages.append("Invalid input body. Expected `fields` to be a list")
            return False
        else:
            probable_fields = ["image_id", "descriptions", "tag_data"]
            self.input["fields"] = list(set(self.input.get('fields')) & set(probable_fields))

        return True

    @property
    def is_valid(self):
        pass
