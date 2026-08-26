from commands.base_command import BaseCommand
from models.metadata.metadata_models import EntityType, MonetizationStatus
from dao.metadata_dao import image_metadata_dao


class UpdateMonetizationStatus(BaseCommand):
    def __init__(self, public_address: str, entity_id: str, entity_type: EntityType,
                 monetization_status: MonetizationStatus):
        super(UpdateMonetizationStatus, self).__init__(public_address)
        self.entity_id = entity_id
        self.entity_type = entity_type
        self.monetization_status = monetization_status

    def execute(self):
        entity = image_metadata_dao.get_doc_by_id(self.entity_id)
        if entity["uploaded_by"] != self.public_address:
            self.successful = False
            self.messages.append("Operation not permitted for user")
            return
        if entity["type"] != self.entity_type:
            self.successful = False
            self.messages.append("Invalid entity type")
            return

        entity["monetization_status"] = self.monetization_status
        image_metadata_dao.update_doc(self.entity_id, entity)
        self.successful = True
