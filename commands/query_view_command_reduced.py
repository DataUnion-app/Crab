from enum import Enum
from typing import Optional

from commands.base_command import BaseCommand
from dao.metadata_dao import image_metadata_dao
from dao.bounty_dao import bounty_dao
from dao.entity_list_dao import entity_list_dao
from models.db_name import DatabaseName


class QueryViewCommandReduced(BaseCommand):
    """
    A generic class which will allow querying data from views from all the databases with reduce.
    Use this to create general stats that can be accessed by anyone.
    The result data should be passed as it is without any processing.
    If result of database query needs further processing, e.g. joining data from two views, create a new Command and
    call QueryViewCommand twice.
    """

    def __init__(self, db_name: DatabaseName, design_doc: str, view_name: str,
                 group_level: Optional[int] = 0, public_address: Optional[str] = None):
        super(QueryViewCommandReduced, self).__init__(public_address=public_address)
        self.design_doc = design_doc
        self.view_name = view_name
        self.group_level = group_level

        '''
         Each view should have an access type defined from the ViewQueryType
        '''
        self.allowed_design_docs = {

            DatabaseName.metadata: {
                "brainstem": {
                    "recording-durations": {
                        "group_level": 0
                    }
                }
            }
        }

        self.db_name = db_name

    def execute(self):
        if self.db_name not in list(self.allowed_design_docs.keys()):
            self.successful = False
            self.messages.append(f"Query on db [{self.db_name}] not allowed")
            return

        if self.design_doc not in list(self.allowed_design_docs[self.db_name].keys()):
            self.successful = False
            self.messages.append(f"Query on design doc [{self.design_doc}] not allowed")
            return

        if self.view_name not in list(self.allowed_design_docs[self.db_name][self.design_doc].keys()):
            self.successful = False
            self.messages.append(f"Query on view  [{self.view_name}] not allowed")
            return

        default_group_level = self.allowed_design_docs[self.db_name][self.design_doc][self.view_name]["group_level"]
        self.group_level = self.group_level if self.group_level else default_group_level

        dao = None
        if self.db_name == DatabaseName.metadata:
            dao = image_metadata_dao
        elif self.db_name == DatabaseName.bounty:
            dao = bounty_dao
        elif self.db_name == DatabaseName.entity_list:
            dao = entity_list_dao

        data = dao.query_view_by_key_range(self.design_doc, self.view_name, None, None, self.group_level)
        rows = data["rows"]
        result = [r["value"] for r in rows]
        self.successful = True
        return result
