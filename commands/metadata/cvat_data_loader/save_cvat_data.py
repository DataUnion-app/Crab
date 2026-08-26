import datetime

from commands.base_command import BaseCommand
from dao.metadata_dao import image_metadata_dao
from dao.bounty_dao import bounty_dao


class SaveCvatDataCommand(BaseCommand):
    def __init__(self, public_address: str, bounty_id: str, data: dict):
        super().__init__(public_address)
        self.data = data
        self.bounty_id = bounty_id

    def execute(self):
        bounty = bounty_dao.get_doc_by_id(self.bounty_id)
        valid_ids = [value for value in bounty['entity_ids'] if value in self.data.keys()]

        if bounty.get('cvat_annotation') is None:
            bounty['cvat_annotation'] = {}

        for image_id in valid_ids:
            annotation = self.data[image_id]

            if bounty['cvat_annotation'].get(image_id) is None:
                bounty['cvat_annotation'][image_id] = []

            if len(annotation['label']) > 1000:
                self.successful = False
                self.messages.append(f"Label more than 1000 chars not allowed.")
                return

            if annotation.get('segmentation') and len(annotation['segmentation']) > 1000:
                self.successful = False
                self.messages.append(f"segmentation more than 1000 chars not allowed.")
                return

            if annotation.get('segmentation_url') and len(annotation['segmentation_url']) > 1000:
                self.successful = False
                self.messages.append(f"segmentation_url more than 1000 chars not allowed.")
                return

            if len(annotation['annotator_email']) > 1000:
                self.successful = False
                self.messages.append(f"annotator_email more than 1000 chars not allowed.")
                return

            if type(annotation['acceptance_rate']) != float \
                    or annotation['acceptance_rate'] < 0 \
                    or annotation['acceptance_rate'] > 1:
                self.successful = False
                self.messages.append(f"acceptance_rate should be between 0 and 1")
                return

            if len(annotation['bbox']) != 4 or not (all(isinstance(x, float) for x in annotation['bbox'])):
                self.successful = False
                self.messages.append(f"bbox len should be 4 and type should be float")
                return

            bounty['cvat_annotation'][image_id].append({
                'created_at': datetime.datetime.utcnow().isoformat(),
                'created_by': self.public_address,
                'label': annotation['label'],
                'segmentation': annotation.get('segmentation'),
                'segmentation_url': annotation.get('segmentation_url'),
                'bbox': annotation['bbox'],
                'annotator_email': annotation['annotator_email'],
                'acceptance_rate': annotation['acceptance_rate']
            })

        bounty_dao.save(self.bounty_id, bounty)
        self.successful = True
