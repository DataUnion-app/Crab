from enum import Enum
from typing import Optional, List

from commands.base_command import BaseCommand
from dao.metadata_dao import image_metadata_dao
from dao.bounty_dao import bounty_dao
from dao.entity_list_dao import entity_list_dao
from models.User import UserRoleType
from models.db_name import DatabaseName
from dao.static_data_dao import static_data_dao
from dao.users_dao import user_dao
from dao.others_dao import others_db
from dao.missions_dao import missions_dao

class ViewQueryType(str, Enum):
    """
    Couchdb key for the view should be in the format: 'public_address'
    """
    user_id = "key"

    keys = "keys"
    key_range = "key_range"

    """
    Couchdb key for the view should be in the format: '["public_address", "doc_id"]'
    """
    user_created_doc_id = "id"

    """
    Couchdb key for the view should be in the format: 'doc_id'.
    The data of the is view will be accessible to every user.
    So, do not emit any data from the document that should have restricted access.
    """
    public_entity_id = "public_entity_id"

    """
    Query all emits from couchdb
    """
    all = "all"


class QueryViewCommand(BaseCommand):
    """
    A generic class which will allow querying data from views from all the databases.
    The result data should be passed as it is without any processing.
    If result of database query needs further processing, e.g. joining data from two views, create a new Command and
    call QueryViewCommand twice.
    """

    def __init__(self, public_address: str, db_name: DatabaseName, design_doc: str, view_name: str,
                 query_type: ViewQueryType, doc_id=Optional[str], roles: List[UserRoleType] = [UserRoleType.User],
                 attachments: bool = False,
                 include_docs: bool = False):
        super(QueryViewCommand, self).__init__(public_address=public_address, roles=roles)
        self.design_doc = design_doc
        self.view_name = view_name

        '''
         Each view should have an access type defined from the ViewQueryType
        '''
        self.query_type = query_type
        self.db_name = db_name
        self.doc_id = doc_id
        self.include_docs = include_docs
        if self.roles is None:
            self.roles: List[UserRoleType] = [UserRoleType.User]

        self.attachments = attachments

    def execute(self):

        supported_views_list = self.get_allowed_design_docs_list()
        view_config = next((x for x in supported_views_list
                            if (x['db_name'] == self.db_name
                                and self.design_doc == x['design-doc']
                                and self.view_name == x['view'])),
                           None)

        if view_config is None:
            self.successful = False
            self.messages.append(
                f"Query on db [{self.db_name}] + design-doc [{self.design_doc}] + view [{self.view_name}] not allowed")
            return
        if len(list(set(self.roles) & set(view_config["access_roles"]))) == 0:
            self.successful = False
            self.messages.append(
                f"Access not allowed")
            return

        dao = None
        if self.db_name == DatabaseName.metadata:
            dao = image_metadata_dao
        elif self.db_name == DatabaseName.bounty:
            dao = bounty_dao
        elif self.db_name == DatabaseName.entity_list:
            dao = entity_list_dao
        elif self.db_name == DatabaseName.static_data:
            dao = static_data_dao
        elif self.db_name == DatabaseName.users:
            dao = user_dao
        elif self.db_name == DatabaseName.other:
            dao = others_db
        elif self.db_name == DatabaseName.missions:
            dao = missions_dao
        key = None
        if self.query_type == ViewQueryType.user_id:
            key = f"\"{self.public_address}\""
        elif self.query_type == ViewQueryType.user_created_doc_id:
            key = f"[\"{self.public_address}\",\"{self.doc_id}\"]"
        elif self.query_type == ViewQueryType.public_entity_id:
            key = f"\"{self.doc_id}\""

        if self.query_type == ViewQueryType.all:
            data = dao.query_view(self.design_doc, self.view_name, skip=0, limit=10 ** 6, attachments=self.attachments,
                                  include_docs=self.include_docs)
        else:
            data = dao.query_view_by_keys(self.design_doc, self.view_name, [key])
        rows = data["rows"]
        
        result = [r["value"] for r in rows]
        self.successful = True
        return result

    def get_allowed_design_docs_list(self) -> List[object]:
        return [{
            "db_name": DatabaseName.entity_list,
            "design-doc": "bounty-entity-list",
            "view": "bounty-progress-stats",
            "view-query_type": ViewQueryType.user_created_doc_id,
            "access_roles": [UserRoleType.User]
        }, {
            "db_name": DatabaseName.entity_list,
            "design-doc": "entity-search-stats",
            "view": "entity-search-stats",
            "view-query_type": ViewQueryType.user_created_doc_id,
            "access_roles": [UserRoleType.User]
        }, {
            "db_name": DatabaseName.bounty,
            "design-doc": "bounty-info",
            "view": "user-bounty",
            "view-query_type": ViewQueryType.user_created_doc_id,
            "access_roles": [UserRoleType.User]
        }, {
            "db_name": DatabaseName.bounty,
            "design-doc": "bounty-info",
            "view": "bounty-id",
            "view-query_type": ViewQueryType.user_created_doc_id,
            "access_roles": [UserRoleType.User]
        }, {
            "db_name": DatabaseName.metadata,
            "design-doc": "wedatanation",
            "view": "user-contributions",
            "view-query_type": ViewQueryType.user_created_doc_id,
            "access_roles": [UserRoleType.User]
        }, {
            "db_name": DatabaseName.metadata,
            "design-doc": "brainstem",
            "view": "per-user-contribution",
            "view-query_type": ViewQueryType.user_id,
            "access_roles": [UserRoleType.User]
        }, {
            "db_name": DatabaseName.metadata,
            "design-doc": "brainstem",
            "view": "compute-data",
            "view-query_type": ViewQueryType.all,
            "access_roles": [UserRoleType.Compute_Job]
        }, {
            "db_name": DatabaseName.static_data,
            "design-doc": "wedatanation",
            "view": "apps",
            "view-query_type": ViewQueryType.public_entity_id,
            "access_roles": [UserRoleType.User]
        }, {
            "db_name": DatabaseName.users,
            "design-doc": "user-info",
            "view": "avatar",
            "view-query_type": ViewQueryType.user_id,
            "access_roles": [UserRoleType.User]
        }, {
            "db_name": DatabaseName.users,
            "design-doc": "user-info",
            "view": "generated-avatar",
            "view-query_type": ViewQueryType.user_id,
            "access_roles": [UserRoleType.User]
        }, {
            "db_name": DatabaseName.metadata,
            "design-doc": "wedatanation",
            "view": "user-metadata",
            "view-query_type": ViewQueryType.user_id,
            "access_roles": [UserRoleType.User]
        }, {
            "db_name": DatabaseName.static_data,
            "design-doc": "wedatanation",
            "view": "messages",
            "view-query_type": ViewQueryType.all,
            "access_roles": [UserRoleType.User]
        }, {
            "db_name": DatabaseName.other,
            "design-doc": "ncight",
            "view": "user-ranks",
            "view-query_type": ViewQueryType.all,
            "access_roles": [UserRoleType.User]
        }, {
            "db_name": DatabaseName.metadata,
            "design-doc": "brainstem",
            "view": "downloadables",
            "view-query_type": ViewQueryType.all,
            "access_roles": [UserRoleType.download]
        }, {
            "db_name": DatabaseName.missions,
            "design-doc": "hmt_reward",
            "view": "ready_to_pay_missions",
            "view-query_type": ViewQueryType.all,
            "access_roles": [UserRoleType.reward_oracle]
        }, {
            "db_name": DatabaseName.bounty,
            "design-doc": "bounty-info",
            "view": "all",
            "view-query_type": ViewQueryType.all,
            "access_roles": [UserRoleType.User]
        }, {
            "db_name": DatabaseName.metadata,
            "design-doc": "wedatanation",
            "view": "survey_responses",
            "view-query_type": ViewQueryType.public_entity_id,
            "access_roles": [UserRoleType.User]
        }, {
            "db_name": DatabaseName.metadata,
            "design-doc": "wedatanation",
            "view": "my-surveys",
            "view-query_type": ViewQueryType.user_id,
            "access_roles": [UserRoleType.User]
        }
        ]
