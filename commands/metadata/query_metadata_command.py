from dao.metadata_dao import image_metadata_dao
from commands.base_command import BaseCommand
from config import config
from models.metadata.annotations.annotation_type import AnnotationType
import logging
import random

from models.metadata.metadata_models import Source, EntityType, EntitySubType


class QueryMetadataCommand(BaseCommand):

    def __init__(self, public_address: str, page: int, status: str, fields: list = [],
                 annotation_type: AnnotationType = AnnotationType.TextTag, entity_type: str = "image",
                 tags: list = None, bounty: str = "general", shuffle: bool = False):
        super().__init__()
        self.annotation_type = annotation_type
        self.input = {
            "public_address": public_address,
            "page": page,
            "status": status,
            "fields": fields,
        }
        self.image_metadata_dao = image_metadata_dao
        self.tags = tags
        self.entity_type = entity_type
        self.bounty = bounty
        self.shuffle = shuffle

    def execute(self):

        is_valid = self.validate_input()

        if is_valid is False:
            self.successful = False
            return
        self.successful = False

        result = []

        if self.annotation_type in [AnnotationType.BoundingBox, AnnotationType.Anonymization, AnnotationType.TextTag,
                                    AnnotationType.Pixel]:
            result = self.image_metadata_dao.query_ids_not_annotated_by_user(
                self.input["status"], self.input["page"], self.input["public_address"], self.annotation_type,
                self.bounty,
                self.entity_type,
                self.tags
            )
        else:
            self.successful = False
            self.messages.append("Unsupported annotation type for querying metadata.")
            return

        if self.shuffle:
            random.shuffle(result['result'])

        self.successful = True
        return result

    def validate_input(self):
        if self.input is None:
            self.messages.append("Empty input")
            return False

        if self.input.get("status") is None:
            self.messages.append("Missing status")
            return False

        if self.input.get("public_address") is None:
            self.messages.append("Missing public_address")
            return False

        if self.input.get("page") is None:
            self.messages.append("Missing page")
            return False
        elif not isinstance(self.input.get("page"), int):
            self.messages.append("Page is not a number")
            return False

        if self.input.get("fields") is None:
            self.messages.append("Missing fields")
            return False
        elif not isinstance(self.input.get("fields"), list):
            self.messages.append("Invalid input body. Expected `fields` to be a list")
            return False
        else:
            probable_fields = ["image_id", "descriptions", "tags"]
            self.input["fields"] = list(
                set(self.input.get("fields")) & set(probable_fields)
            )

        try:
            AnnotationType(self.annotation_type)
        except ValueError as e:
            logging.exception(e, exc_info=True)
            self.messages.append(str(e))
            return False

        return True

    @property
    def is_valid(self):
        pass


'''
Query the docs with child-parent setup, and taking source into consideration.
'''


class QueryMetadataCommand2(BaseCommand):
    def __init__(self, public_address: str, source: Source, skip: int, limit: int, annotation_type: AnnotationType,
                 entity_type: EntityType, entity_sub_type: EntitySubType):
        super(QueryMetadataCommand2, self).__init__(public_address)
        self.source = source
        self.skip = skip
        self.limit = limit
        self.annotation_type = annotation_type
        self.entity_type = entity_type
        self.entity_sub_type = entity_sub_type

    def execute(self):
        query = {
            "selector": {
                "source": self.source,
                "parent": True,
                "user_submissions": {
                    self.annotation_type: {
                        "$not": {"$elemMatch": {
                            "$eq": self.public_address
                        }}
                    }
                }
            },
            "skip": self.skip,
            "limit": self.limit,
            "fields": ["public", "doc_id"]
        }
        self.successful = True

        result = image_metadata_dao.query_data(query)
        return result
