import logging
import os
from datetime import datetime
import mimetypes
from typing import List, Tuple

from flask import stream_with_context, Response
from werkzeug.datastructures import Headers

from commands.base_command import BaseCommand
from commands.query_view_command import QueryViewCommand, ViewQueryType
from dao.base_dao import DBResultError
from dao.bounty_dao import bounty_dao
from dao.entity_list_dao import entity_list_dao
from dao.batch_dao import batch_dao
from models.User import UserRoleType
from models.bounty import BountyType, BOUNTY_ID_PREFIX, BountyStatus, Location
from models.db_name import DatabaseName
from models.entity_list_models import EntityListType
from models.metadata.metadata_models import EntityType, Source


class CreateBountyCommand(BaseCommand):
    ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "PNG", "JPG", "JPEG", "GIF"}

    # entity_list_ids = list of entity list ids to be used for verification/annotation bounty

    def __init__(self, public_address: str, company_name: str, company_description: str, bounty_type: BountyType,
                 bounty_name: str, bounty_description: str, start_date: datetime, end_date: datetime,
                 company_image_path: str,
                 bounty_image_path: str, tags: list, samples: list, image_requirements: str, image_format: list,
                 entity_list_name: str, product_id: str, special_instructions: str, minimum_amount_stored: int, minimum_amount_returned: int, amount_of_items: int, amount_of_reward: int, location: Location, qr_code:str, batch_ids:list, collection_point: Location, collection_point_description:str, image_count: int = None, number_of_verifications: int = None, number_of_annotations: int = None,
                 entity_list_ids: List[str] = (), access_to_user_roles=tuple(UserRoleType.User)):
        super(CreateBountyCommand, self).__init__(public_address)

        if access_to_user_roles is None or len(access_to_user_roles) == 0:
            access_to_user_roles = [UserRoleType.User]

        self.bounty_description = bounty_description
        self.end_date = end_date
        self.start_date = start_date
        self.bounty_name = bounty_name
        self.bounty_type = bounty_type
        self.company_description = company_description
        self.company_name = company_name
        self.bounty_dao = bounty_dao
        self.company_image = company_image_path
        self.bounty_image = bounty_image_path
        self.tags = tags
        self.samples = samples
        self.image_requirements = image_requirements
        self.image_format = image_format
        self.image_count = image_count
        self.number_of_verifications = number_of_verifications
        self.number_of_annotations = number_of_annotations
        self.entity_list_name = entity_list_name
        self.entity_list_ids = entity_list_ids
        self.access_to_user_roles = access_to_user_roles
        self.product_id = product_id
        self.special_instructions = special_instructions
        self.minimum_amount_stored = minimum_amount_stored
        self.minimum_amount_returned = minimum_amount_returned
        self.amount_of_items = amount_of_items
        self.amount_of_reward = amount_of_reward
        self.location = location
        self.collection_point =  collection_point
        self.collection_point_description = collection_point_description
        self.qr_code = qr_code
        self.batch_ids = batch_ids

    def execute(self):
        if not self.validate_params():
            self.successful = False
            return
        if self.bounty_type == BountyType.IMAGE_UPLOAD:
            doc_id = self.create_upload_bounty()
        elif self.bounty_type == BountyType.IMAGE_ANNOTATE:
            doc_id = self.create_annotation_bounty()
        elif self.bounty_type == BountyType.IMAGE_VERIFY:
            doc_id = self.create_verification_bounty()
        else:
            self.messages.append(f"Invalid bounty type {self.bounty_type}")
            return
        logging.info("Created new bounty [%s]", doc_id)

        if self.company_image:
            c_mime_type = mimetypes.guess_type(self.company_image)[0]
            result1 = self.bounty_dao.save_attachment(f'company_image', self.company_image, doc_id, c_mime_type)
            if result1 is False:
                self.successful = False
                self.messages.append(f'Cannot save image [{self.company_image}] to database.')
                return
            os.remove(self.company_image)

        b_mime_type = mimetypes.guess_type(self.bounty_image)[0]
        result2 = self.bounty_dao.save_attachment(f'bounty_image', self.bounty_image, doc_id, b_mime_type)
        if result2 is False:
            self.successful = False
            self.messages.append(f'Cannot save image [{self.bounty_image}] to database.')
            return

        os.remove(self.bounty_image)

        self.successful = True
        return {
            'id': doc_id
        }

    def get_new_bounty_base_document(self) -> (str, dict):

        doc_id = self.bounty_dao.generate_new_doc_id()

        status = BountyStatus.IN_PROGRESS if self.start_date.date() == datetime.utcnow().today().date() \
            else BountyStatus.CREATED

        entity_list_id = entity_list_dao.create_list(public_address=self.public_address, entity_type=EntityType.image,
                                                     entity_ids=[],
                                                     entity_list_type=EntityListType.BOUNTY, name=self.entity_list_name)
        batch_dao.set_bounty_id(self.batch_ids, doc_id)
        document = {'company_name': self.company_name,
                    'company_description': self.company_description,
                    'document_type': BOUNTY_ID_PREFIX,
                    'bounty_type': self.bounty_type,
                    'bounty_name': self.bounty_name,
                    'bounty_description': self.bounty_description,
                    'company_image': self.company_image,
                    'bounty_image': self.bounty_image,
                    'start_date': self.start_date.isoformat(),
                    'end_date': self.end_date.isoformat(),
                    'created_by': self.public_address,
                    'created_at': datetime.utcnow().replace(microsecond=0).isoformat(),
                    'updated_at': datetime.utcnow().replace(microsecond=0).isoformat(),
                    'updated_by': self.public_address,
                    'tags': self.tags,
                    'sample_data_list': self.samples,
                    'number_of_verifications': self.number_of_verifications,
                    'status': status,
                    'missions': [],
                    'missions_count': 0,
                    'entity_list_id': entity_list_id,
                    'access_to_user_roles': self.access_to_user_roles,
                    'product_id': self.product_id,
                    'special_instructions': self.special_instructions,
                    'minimum_amount_stored': self.minimum_amount_stored,
                    'minimum_amount_returned': self.minimum_amount_returned,
                    'amount_of_items': self.amount_of_items,
                    'amount_of_reward': self.amount_of_reward,
                    'location': self.location,
                    'collection_point': self.collection_point,
                    'collection_point_description': self.collection_point_description,
                    'qr_code': self.qr_code,
                    'batch_ids': self.batch_ids
                    }
        return doc_id, document

    def create_annotation_bounty(self) -> str:
        doc_id, document = self.get_new_bounty_base_document()
        document['number_of_annotations'] = self.number_of_annotations
        document['entity_list_ids'] = self.entity_list_ids
        document['per_user_allocated_entity_ids_index'] = {}

        if not self.number_of_annotations or self.number_of_annotations <= 0:
            raise CannotCreateBountyException(f"Number of required annotations should be greater than 0")

        entity_ids = self.validate_entity_list_ids_and_get_entity_ids()
        document["entity_ids"] = entity_ids
        document["entity_id_allocations"] = {i: 0 for i in entity_ids}

        self.bounty_dao.save(doc_id, document)

        return doc_id

    def create_verification_bounty(self) -> str:
        doc_id, document = self.get_new_bounty_base_document()
        
        if not self.number_of_verifications or self.number_of_verifications <= 0:
            raise CannotCreateBountyException(f"Number of required verifications should be greater than 0")

        document['number_of_verifications'] = self.number_of_verifications
        document['entity_list_ids'] = self.entity_list_ids
        document['per_user_allocated_entity_ids_index'] = {}
        entity_ids = self.validate_entity_list_ids_and_get_entity_ids()
        document["entity_ids"] = entity_ids
        document["entity_id_allocations"] = {i: 0 for i in entity_ids}

        self.bounty_dao.save(doc_id, document)
        return doc_id

    def create_upload_bounty(self) -> str:
        doc_id, document = self.get_new_bounty_base_document()
        document['image_requirements'] = self.image_requirements
        document['image_format'] = self.image_format
        document['image_count'] = self.image_count

        self.bounty_dao.save(doc_id, document)

        return doc_id

    def allowed_file(self, filename: str):
        return "." in filename and filename.rsplit(".", 1)[1].lower() in CreateBountyCommand.ALLOWED_EXTENSIONS

    def validate_params(self):
        if len(self.company_name) > 200:
            self.messages.append("Company name should be up to 200 characters.")
        if len(self.company_description) > 2000:
            self.messages.append("Company description should be up to 2000 characters.")
        if len(self.bounty_name) > 200:
            self.messages.append("Bounty name should be up to 200 characters.")
        if len(self.bounty_description) > 2000:
            self.messages.append("Bounty description should be up to 2000 characters.")
        if not isinstance(self.start_date, datetime):
            self.messages.append("Bounty description should be up to 2000 characters.")
        if self.start_date.date() < datetime.today().date():
            self.messages.append("Start date should be at least today.")
        if self.start_date.date() < datetime.today().date():
            self.messages.append("Start date should be greater than today.")
        if self.end_date.date() < datetime.today().date() or self.end_date.date() <= self.start_date.date():
            self.messages.append("End date should be greater than today and the start date.")
        if self.end_date.date() < datetime.today().date() or self.end_date.date() <= self.start_date.date():
            self.messages.append("End date should be greater than today and the start date.")
        if self.company_image != None and not self.allowed_file(self.company_image):
            self.messages.append(f"Company image extension not allowed.")
        if self.bounty_image != None and not self.allowed_file(self.bounty_image):
            self.messages.append(f"Bounty image extension not allowed.")
        if self.entity_list_name != None and not self.entity_list_name:
            self.messages.append(f"entity_list_name cannot be empty")

        if self.messages:
            return False
        return True

    def validate_entity_list_ids_and_get_entity_ids(self) -> Tuple:
        entity_ids = set()
        if len(self.entity_list_ids) == 0:
            raise CannotCreateBountyException(f"Missing 'entity_list_ids' for bounty type {self.bounty_type}")

        for list_id in self.entity_list_ids:
            exists = entity_list_dao.exists(list_id)
            if not exists:
                raise CannotCreateBountyException(f"Invalid entity list id [{list_id}]")

            entity_list = entity_list_dao.get_doc_by_id(list_id)

            if entity_list["entity_list_type"] == EntityListType.PRIVATE \
                    and entity_list["public_address"] != self.public_address:
                raise CannotCreateBountyException(
                    f"Invalid entity list [{list_id}] is private and not owned by {self.public_address}")

            if entity_list["entity_list_type"] == EntityListType.BOUNTY:
                raise CannotCreateBountyException(
                    f"Invalid entity list [{list_id}] is a bounty. Use a public or a private entity list")
            entity_ids.update(entity_list["entity_ids"])

        return tuple(entity_ids)


class GetBountyList(BaseCommand):
    def __init__(self, public_address: str, roles: List[UserRoleType], source: Source):
        super(GetBountyList, self).__init__(public_address, roles, source)
        self.bounty_dao = bounty_dao
    
    def execute(self):
        result = self.bounty_dao.get_bounties_by_user(self.public_address, self.roles)
        self.successful = True
        bounty_list = []
        for r in result:
            # TODO: Use a couchdb view to get the information about accepted/rejected/total count

            entity_list_id = r['entity_list_id']
            entity_list = entity_list_dao.get_doc_by_id(entity_list_id)
            all_entities = set(entity_list["entity_ids"])
            accepted_entities = set(entity_list.get("accepted_image_ids", []))
            accepted_entity_count = len(set(all_entities) & set(accepted_entities))

            rejected_entities = set(entity_list.get("rejected_image_ids", []))
            rejected_entity_count = len(set(all_entities) & set(rejected_entities))

            total_entities_count = len(accepted_entities)
            bounty_information = {
                'id': r['_id'],
                'bounty_name': r['bounty_name'],
                'bounty_description': r['bounty_description'],
                'company_name': r['company_name'],
                'company_description': r['company_description'],
                'company_image_url': 'todo',
                'bounty_image_url': 'todo',
                'start_date': r['start_date'],
                'end_date': r['end_date'],
                'tags': r.get('tags', []),
                'sample_data_list': r.get('sample_data_list', []),
                'image_requirements': r.get('image_requirements', None),
                'image_format': r.get('image_format', []),
                'image_count': r.get('image_count'),
                'number_of_verifications': r.get('number_of_verifications'),
                'number_of_annotations': r.get('number_of_annotations'),
                'status': r.get('status'),
                'bounty_type': r.get('bounty_type'),
                'accepted_entity_count': None,
                'rejected_entity_count': None,
                'total_entity_count': total_entities_count,
                'entity_list_id': entity_list_id,
            }
            if self.source == Source.recyclium:
                bounty_information['product_id'] = r.get('product_id'),
                bounty_information['special_instructions'] = r.get('special_instructions'),
                bounty_information['minimum_amount_stored'] = r.get('minimum_amount_stored'),
                bounty_information['minimum_amount_returned'] = r.get('minimum_amount_returned'),
                bounty_information['amount_of_items'] = r.get('amount_of_items'),
                bounty_information['amount_of_reward'] = r.get('amount_of_reward'),
                bounty_information['location'] = r.get('location')
            if r["bounty_type"] == BountyType.IMAGE_UPLOAD:
                bounty_information["accepted_entity_count"] = accepted_entity_count
                bounty_information["rejected_entity_count"] = rejected_entity_count

            bounty_list.append(bounty_information)

        return bounty_list


class GetBountyImage(BaseCommand):

    def __init__(self, bounty_id: str, image_type: str):
        super(GetBountyImage, self).__init__()
        self.bounty_id = bounty_id
        self.image_type = image_type
        self.bounty_dao = bounty_dao

    def execute(self):
        # TODO: Add validations
        try:
            response = self.bounty_dao.get_attachment(self.bounty_id, self.image_type)
            headers = Headers()
            headers.add('Content-Type', response.headers["Content-Type"])
            headers.add('Content-Disposition', f'attachment; filename="{self.image_type}"')

            self.successful = True

            return Response(stream_with_context(response.iter_content(chunk_size=2048)), headers=headers)
        except DBResultError as e:
            self.successful = False
            self.messages.append(str(e))
            return


class CannotCreateBountyException(Exception):
    def __init__(self, message: str):
        self.message = message
        super().__init__(self.message)

    def __str__(self):
        return f'[{self.message}'


class UpdateBountyProgress(BaseCommand):
    def __init__(self, bounty_id: str, entity_ids: List[str]):
        super(UpdateBountyProgress, self).__init__()
        self.bounty_id = bounty_id
        self.entity_ids = entity_ids

    def execute(self):
        # TODO: Optimize db call
        bounty = bounty_dao.get_doc_by_id(self.bounty_id)

        entity_list_id = bounty["entity_list_id"]
        entity_list_dao.update_bounty_progress(entity_list_id, entity_ids=self.entity_ids)

        list_size = entity_list_dao.get_entity_list_length(entity_list_id)
        if bounty['bounty_type'] == BountyType.IMAGE_UPLOAD and list_size >= bounty['image_count']:
            bounty['updated_at'] = datetime.utcnow().isoformat()
            bounty['status'] = BountyStatus.COMPLETED
            bounty_dao.update_doc(self.bounty_id, bounty)
        self.successful = True
        return


class GetImagesByBounty(BaseCommand):

    def __init__(self, bounty_id: str):
        super(GetImagesByBounty, self).__init__()
        self.bounty_id = bounty_id
        self.bounty_dao = bounty_dao

    def execute(self):
        try:
            bounty = self.bounty_dao.get_doc_by_id(self.bounty_id)
            entity_list_id = bounty.get('entity_list_id')

            if not entity_list_id:
                self.successful = False
                self.messages.append('entity_list_id does not exist for the bounty')
                return

            entity_list_obj = entity_list_dao.get_doc_by_id(entity_list_id)
            entity_ids = entity_list_obj.get('entity_ids', [])
            self.successful = True

            return entity_ids
        except Exception as e:
            self.successful = False
            self.messages.append(str(e))
            return


class HandleImagesOfBounty(BaseCommand):

    def __init__(self, public_address: str, bounty_id: str, accepted_images=[], rejected_images=[]):
        super(HandleImagesOfBounty, self).__init__()
        self.public_address = public_address
        self.bounty_id = bounty_id
        self.accepted_images = accepted_images
        self.rejected_images = rejected_images
        self.bounty_dao = bounty_dao
        self.entity_list_dao = entity_list_dao

    def execute(self):
        try:
            bounty = self.bounty_dao.get_doc_by_id(self.bounty_id)

            # Validate the bounty creator
            if bounty.get('created_by') != self.public_address:
                self.successful = False
                self.messages.append('The user is not the owner of the bounty!')
                return

            entity_list_id = bounty.get('entity_list_id')

            if not entity_list_id:
                self.successful = False
                self.messages.append('entity_list_id does not exist for the bounty')
                return

            entity_list_obj = entity_list_dao.get_doc_by_id(entity_list_id)

            accepted_or_rejected_images = set(
                entity_list_obj.get('accepted_image_ids', []) + entity_list_obj.get('rejected_image_ids', []))

            new_image_ids = set(self.accepted_images + self.rejected_images)

            already_present = list(set(accepted_or_rejected_images) & set(new_image_ids))
            if len(already_present) > 0:
                self.successful = False
                self.messages.append(f"Image ids already accepted/rejected {already_present}")
                return
            entity_list_obj['accepted_image_ids'] = list(
                set(entity_list_obj.get('accepted_image_ids', []) + self.accepted_images))
            entity_list_obj['rejected_image_ids'] = list(
                set(entity_list_obj.get('rejected_image_ids', []) + self.rejected_images))
            self.entity_list_dao.update_doc(entity_list_id, entity_list_obj)

            self.successful = True

            if '_rev' in entity_list_obj:
                entity_list_obj.pop('_rev')
            if '_id' in entity_list_obj:
                entity_list_obj['id'] = entity_list_obj.pop('_id')

            return entity_list_obj
        except Exception as e:
            self.successful = False
            self.messages.append(str(e))
            return


class GetUserCreatedBountyById(BaseCommand):
    def __init__(self, public_address: str, bounty_id: str):
        super(GetUserCreatedBountyById, self).__init__(public_address)
        self.doc_id = bounty_id

    def execute(self):
        c1 = QueryViewCommand(self.public_address, DatabaseName.bounty, "bounty-info", "user-bounty",
                              ViewQueryType.user_created_doc_id,
                              self.doc_id)

        result = c1.execute()
        if len(result) == 0:
            self.successful = False
            self.messages.append("Bounty not found or access is denied.")
            return
        bounty_information = result[0]
        c2 = QueryViewCommand(self.public_address, DatabaseName.entity_list, "bounty-entity-list",
                              "bounty-progress-stats",
                              ViewQueryType.user_created_doc_id,
                              result[0]["entity_list_id"])
        result2 = c2.execute()[0]
        bounty_information.update(result2)
        self.successful = c1.successful and c2.successful
        return result


class GetLeastCompletedBounty(BaseCommand):

    def __init__(self, public_address: str):
        super(GetLeastCompletedBounty, self).__init__(public_address)

    def execute(self):
        pass
