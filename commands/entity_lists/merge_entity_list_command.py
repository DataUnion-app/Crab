from datetime import datetime
from typing import List

from commands.base_command import BaseCommand
from dao.base_dao import DBResultError
from dao.entity_list_dao import entity_list_dao
from models.entity_list_models import EntityListType


class MergeEntityListsCommand(BaseCommand):
    def __init__(self, public_address: str, sources: List[str], destination: str):
        super(MergeEntityListsCommand, self).__init__(public_address=public_address)
        self.sources = sources
        self.destination = destination

    def execute(self):
        try:

            destination_entity_list = entity_list_dao.get_doc_by_id(self.destination)
            if destination_entity_list["public_address"] != self.public_address:
                self.messages.append(f"[{self.public_address}] is not owner of destination list.")
                return

            source_entity_ids = set()
            for source in self.sources:
                source_entity_list = entity_list_dao.get_doc_by_id(source)

                if source_entity_list["entity_list_type"] == EntityListType.BOUNTY \
                        or destination_entity_list["entity_list_type"] == EntityListType.BOUNTY:
                    self.messages.append("Operation on Bounty list not permitted.")
                    return

                if source_entity_list["entity_list_type"] == EntityListType.PRIVATE and self.public_address != \
                        source_entity_list["public_address"]:
                    self.messages.append(
                        f"[{self.public_address}] is not owner of source list [{source_entity_list['_id']}].")
                    return
                source_entity_ids = source_entity_ids.union(set(source_entity_list["entity_ids"]))

            destination_entity_list["updated_at"] = datetime.now().replace(microsecond=0).isoformat()
            destination_entity_list["entity_ids"] = list(
                set(destination_entity_list["entity_ids"]).union(source_entity_ids))
            entity_list_dao.update_doc(destination_entity_list["_id"], destination_entity_list)
            self.successful = True

        except DBResultError as e:
            self.messages.append(str(e))
            return

        self.successful = True
        return
