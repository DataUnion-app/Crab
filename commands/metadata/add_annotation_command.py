from typing import List

from commands.base_command import BaseCommand
from commands.bounty.bounty_commands import UpdateBountyProgress
from dao.metadata_dao import image_metadata_dao
from dao.missions_dao import missions_dao
from models.metadata.annotations.NCight_user_metadata import NCightUserMetadata
from models.metadata.annotations.annotation_survey_response import AnnotationSurveyResponse
from models.metadata.annotations.annotation_data_share_report import AnnotationDataShareReport
from models.metadata.annotations.cvat_image_id import CvatImageIdAnnotation
from models.metadata.annotations.location_annotation import LocationAnnotation
from models.metadata.annotations.bounding_box import BoundingBox
from models.metadata.annotations.base_annotation import InvalidInputFieldException, BaseAnnotation
from models.metadata.annotations.anonymization import Anonymization
from models.metadata.annotations.pixel_annotation import PixelAnnotation, PixelBox
from models.metadata.annotations.annotation_type import AnnotationType
from models.metadata.annotations.annotation_peaq_did import AnnotationPeaqDid
import logging

from models.metadata.annotations.text_tag import TagAnnotation
from models.metadata.annotations.true_label_annotation import TrueTag
from models.metadata.metadata_models import Source
from models.missions import MissionStatus


class AddAnnotationCommand(BaseCommand):
    def __init__(self, public_address: str, entity_id: str, annotations: [object], mission_id: str = None,
                 save_to_child_doc=False):
        super(AddAnnotationCommand, self).__init__(public_address)
        self.annotations = annotations
        self.image_id = entity_id
        self.mission_id = mission_id

        # save_to_child_doc indicates v2 of backend. If the true, the annotation is saved to child doc of entity_id
        # Also, in parent doc public address is added to doc["user_submissions"][<annotation_Type>]
        self.save_to_child_doc = save_to_child_doc

    def execute(self):
        if not self.validate_input():
            self.successful = False
            return

        # Search if mission id is not none
        if self.mission_id:
            # Check if mission is assigned to user
            user_mission_information = missions_dao.get_mission_details_for_user(self.public_address, self.mission_id)
            if not user_mission_information:
                self.successful = False
                self.messages.append("Invalid mission id")
                return

            # Check if mission is in progress
            if user_mission_information['status'] not in [MissionStatus.IN_PROGRESS, MissionStatus.READY_TO_START]:
                self.successful = False
                self.messages.append(f"Invalid mission status [{user_mission_information['status']}]")
                return

            # Check if user is submitting annotations for the specified entity in the mission.
            if self.image_id not in user_mission_information['entity_ids']:
                self.successful = False
                self.messages.append(f"Entity id [{self.image_id}] not part of mission [{self.mission_id}]")
                return

        exists, entity_doc = image_metadata_dao.get_if_exists(self.image_id)

        if not exists:
            self.successful = False
            self.messages.append("Entity not found.")
            return

        try:
            try:
                annotations = self.parse_annotations(self.image_id, self.public_address, self.annotations)
            except InvalidInputFieldException as e:
                self.messages.append(str(e))
                self.successful = False
                return

            if self.save_to_child_doc:
                # New backend version where a parent doc can have multiple child docs
                allowed_types = [AnnotationType(e) for e in entity_doc["annotations_required"]]
                for a in annotations:
                    if a.annotation_type not in allowed_types:
                        self.messages.append(f"Not allowed annotation type [{a.annotation_type}] for entity")
                        self.successful = False
                        return
                    if self.public_address in entity_doc["user_submissions"][a.annotation_type]:
                        self.messages.append(f"Already submitted [{a.annotation_type}] for entity")
                        self.successful = False
                        return
                    entity_doc["user_submissions"][a.annotation_type].append(self.public_address)
                # Update parent doc

                child_doc_id = entity_doc["child_docs"][-1]
                image_metadata_dao.add_annotation_to_child_entity(child_doc_id, annotations)

                image_metadata_dao.update_doc(doc_id=entity_doc["_id"], data=entity_doc)

            else:
                # Older backend version where 1 doc = 1 entity
                image_metadata_dao.add_annotation_to_image(self.image_id, annotations)

            if self.mission_id:
                mission_document = missions_dao.get_mission_details_by_id(mission_id=self.mission_id)

                # Update mission progress
                annotation_ids = [a.annotation_id for a in annotations]
                missions_dao.update_progress(self.mission_id, annotation_ids=annotation_ids)

                # Update bounty progress
                bounty_id = mission_document['bounty_id']
                UpdateBountyProgress(bounty_id=bounty_id, entity_ids=annotation_ids).execute()

            self.successful = True

        except KeyError as e:
            self.messages.append(str(e))
            self.successful = False
        except Exception as e:
            logging.exception(e)
            self.messages.append("Unable to process request")
            self.successful = False

    def validate_input(self) -> bool:

        if not isinstance(self.annotations, list):
            self.messages.append("annotations is not a list")
            return False
        return True

    @staticmethod
    def parse_annotations(entity_id: str, public_address: str, inputs: List[dict]) -> List[BaseAnnotation]:
        annotations = []

        for annotation in inputs:
            new_annotation = None
            if annotation["type"] == "box":
                new_annotation = BoundingBox(
                    public_address,
                    entity_id,
                    annotation["tag"],
                    annotation["x"],
                    annotation["y"],
                    annotation["width"],
                    annotation["height"],
                )
            elif annotation["type"] == "anonymization":
                new_annotation = Anonymization(
                    public_address,
                    entity_id,
                    annotation["age"],
                    annotation["gender"],
                    annotation["skin_color"]
                )
            elif annotation["type"] == "dots":
                new_annotation = PixelAnnotation(
                    public_address,
                    entity_id,
                    annotation["tag"],
                    [PixelBox(pixel_box['x'], pixel_box['y'], pixel_box['height'], pixel_box['width']) for
                     pixel_box in annotation['dots']]
                )
            elif annotation["type"] == "location":
                new_annotation = LocationAnnotation(
                    public_address,
                    entity_id,
                    annotation["latitude"],
                    annotation["longitude"],
                    annotation["locality"] if annotation["locality"] else "",
                    annotation["city"] if annotation["city"] else ""
                )
            elif annotation["type"] == "tag":
                new_annotation = TagAnnotation(
                    public_address,
                    entity_id,
                    annotation["tags"]
                )
            elif annotation["type"] == "TrueTag":
                new_annotation = TrueTag(
                    public_address,
                    entity_id,
                    annotation["tags"]
                )
            elif annotation["type"] == "ncight_user_metadata":
                new_annotation = NCightUserMetadata(
                    public_address,
                    entity_id,
                    annotation["data"]
                )
            elif annotation["type"] == "cvat_id":
                new_annotation = CvatImageIdAnnotation(
                    public_address,
                    entity_id,
                    annotation["cvat_image_id"]
                )
            elif annotation["type"] == AnnotationType.survey_response:
                new_annotation = AnnotationSurveyResponse(
                    entity_id,
                    public_address,
                    annotation["data"]
                )
            elif annotation["type"] == AnnotationType.data_share_report:
                new_annotation = AnnotationDataShareReport(
                    entity_id,
                    public_address,
                    annotation["data"]
                )
            elif annotation["type"] == AnnotationType.peaq_did:
                new_annotation = AnnotationPeaqDid(
                    entity_id,
                    public_address,
                    annotation["data"]
                )
            else:
                logging.warning("Unknown annotation type [%s]", annotation["type"])
            annotations.append(new_annotation)
        return annotations


class AddTrueTagAnnotationCommand(BaseCommand):
    def __init__(self, public_address: str, image_id: str, annotations: [object]):
        super(AddTrueTagAnnotationCommand, self).__init__(public_address)
        self.annotations = annotations
        self.image_id = image_id

    def execute(self):
        annotations = []

        if not image_metadata_dao.exists(self.image_id):
            self.successful = False
            self.messages.append("Image not found.")
            return

        try:
            for annotation in self.annotations:
                new_annotation = None
                try:
                    if annotation["type"] == "TrueTag":
                        new_annotation = TrueTag(
                            self.public_address,
                            self.image_id,
                            annotation["tags"]
                        )
                    else:
                        logging.warning("Unknown annotation type [%s]", annotation["type"])
                except InvalidInputFieldException as e:
                    self.messages.append(str(e))
                    self.successful = False
                    return

                annotations.append(new_annotation)
            result = image_metadata_dao.add_annotation_to_image(
                self.image_id, annotations
            )
            if result:
                self.successful = True
            else:
                self.successful = False
        except KeyError as e:
            self.messages.append(str(e))
            self.successful = False
        except Exception as e:
            logging.exception(e)
            self.messages.append("Unable to process request")
            self.successful = False

    def validate_input(self) -> bool:
        return True
