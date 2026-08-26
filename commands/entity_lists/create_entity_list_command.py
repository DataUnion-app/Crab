from typing import List

from commands.base_command import BaseCommand
from dao.base_dao import DBResultError
from dao.entity_list_dao import entity_list_dao
from models.entity_list_models import EntityListType
from models.metadata.annotations.annotation_type import AnnotationType
from models.metadata.metadata_models import EntityType, Source
from dao.metadata_dao import image_metadata_dao


class CreateEntityListCommand(BaseCommand):

    def __init__(self, public_address: str, entity_type: EntityType, visibility: EntityListType, entity_ids: list,
                 name: str, description: str, image: str = None, source: Source = Source.default):
        super(CreateEntityListCommand, self).__init__()
        self.public_address = public_address
        self.entity_type = entity_type
        self.visibility = visibility
        self.entity_ids = entity_ids
        self.description = description
        self.name = name
        self.image = image
        self.source = source

    def execute(self):
        self.successful = True

        description_limit = 2000
        if self.description and len(self.description) > description_limit:
            self.messages.append(f"Description too long. Limit is {description_limit} characters.")
            return

        name_limit = 200
        if self.description and len(self.name) > name_limit:
            self.messages.append(f"Name too long. Limit is {name_limit} characters.")
            return

        guild = entity_list_dao.create_list(self.public_address, self.entity_type, self.entity_ids, self.visibility,
                                              self.name, self.description, image=self.image, source=self.source)

        return guild


class CreateOrUpdateEntityListFromAnnotations(BaseCommand):

    def __init__(self, public_address: str, entity_type: EntityType, visibility: EntityListType,
                 name: str, description: str, annotation_type: AnnotationType, tags: List[str],
                 entity_list_id: str = None, image: str = None):
        super(CreateOrUpdateEntityListFromAnnotations, self).__init__(public_address)
        self.entity_type = entity_type
        self.visibility = visibility
        self.annotation_type = annotation_type
        self.tags = tags
        self.name = name
        self.description = description
        self.entity_list_id = entity_list_id
        self.image = image

    def execute(self):

        entity_ids = []
        try:
            if self.entity_list_id and \
                    entity_list_dao.get_doc_by_id(self.entity_list_id)['public_address'] != self.public_address:
                self.successful = False
                self.messages.append("Operation not permitted.")
                return
        except DBResultError as e:
            self.successful = False
            self.messages.append(str(e))
            return

        if self.annotation_type == AnnotationType.TextTag:

            entities = image_metadata_dao.search_entities_by_tags(entity_type=self.entity_type,
                                                                  annotation_type=self.annotation_type, page=1,
                                                                  query_type="$and",
                                                                  page_size=10 ** 6, fields=['_id'], tags=self.tags)

            entity_ids = [i for i in entities['result']]

        else:
            self.successful = False
            self.messages.append(f"Annotation type [{self.annotation_type}] not supported.")
            return

        try:
            if self.entity_list_id:

                entity_list_dao.add_entities_to_list(self.entity_list_id, entity_ids)
                self.successful = True

                return self.entity_list_id
            else:

                if self.validate() is False:
                    self.successful = False
                    return
                list_id = entity_list_dao.create_list(self.public_address, self.entity_type, entity_ids,
                                                      self.visibility, self.name, self.description, image=self.image)
                self.successful = True
                return list_id
        except DBResultError as e:
            self.successful = False
            self.messages.append(str(e))
            return

    def validate(self) -> bool:
        description_limit = 2000
        if self.description and len(self.description) > description_limit:
            self.messages.append(f"Description too long. Limit is {description_limit} characters.")
            return False

        name_limit = 200
        if self.name and len(self.name) > name_limit:
            self.messages.append(f"Name too long. Limit is {name_limit} characters.")
            return False

        return True
