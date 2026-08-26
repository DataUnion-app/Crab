from commands.base_command import BaseCommand
from config import config
from dao.static_data_dao import StaticDataDao


class GetRoutePermissionDocCommand(BaseCommand):
    def __init__(self):
        super().__init__()

        user = config["couchdb"]["user"]
        password = config["couchdb"]["password"]
        db_host = config["couchdb"]["db_host"]
        metadata_db = config["couchdb"]["static_data_db"]
        self.staticdata_dao = StaticDataDao()
        self.staticdata_dao.set_config(user, password, db_host, metadata_db)

    def execute(self):
        try:
            result = self.staticdata_dao.get_route_permission_doc()
            self.successful = True
        except:
            result = "An error comes up in fetching the route permission data from the database"
            self.successful = False
        return result
