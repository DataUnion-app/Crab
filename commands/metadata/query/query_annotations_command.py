from commands.base_command import BaseCommand
from dao.metadata_dao import image_metadata_dao
from models.metadata.annotations.annotation_type import AnnotationType
import logging


class QueryAnnotationsCommand(BaseCommand):

    def __init__(self, image_ids: [str], annotations: [str]):
        super(QueryAnnotationsCommand, self).__init__()
        self.input = {
            'image_ids': image_ids,
            "annotations": annotations
        }
        self.image_metadata_dao = image_metadata_dao

    def execute(self):

        if not self.validate_input():
            self.successful = False
            return

        self.successful = True
        result = {}
        for annotation in self.input['annotations']:
            res = self.image_metadata_dao.get_annotations_for_images(self.input["image_ids"],
                                                                     AnnotationType[annotation])
            result[annotation] = res

        return result

    def validate_input(self):
        if len(self.input["image_ids"]) > 100:
            self.messages.append("Max 100 images a once.")
            return False

        for field in self.input['annotations']:
            try:
                type = AnnotationType[field]
            except KeyError:
                self.messages.append(f"Invalid field {field}")
                logging.info("Invalid field %s", field)
                return False
        return True
