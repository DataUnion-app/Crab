import logging

from commands.base_command import BaseCommand
from config import config
from dao.static_data_dao import static_data_dao


class CreateRoutePermissionDocCommand(BaseCommand):
    def __init__(self, enable_annotations=False, enable_uploads=True):
        super().__init__()
        self.enable_annotations = enable_annotations
        self.enable_uploads = enable_uploads

    def execute(self):
        try:
            static_data_dao.create_route_permission_doc(self.enable_annotations,
                                                        self.enable_uploads)
            self.successful = True
        except Exception as e:
            logging.exception("Failed to create route permission", e)
            self.successful = False
            self.messages.append("Adding the route permission document is failed")
