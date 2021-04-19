from commands.base_command import BaseCommand
from dao.taxonomy_dao import taxonomy_dao
from datetime import datetime


class AddTaxonomyData(BaseCommand):
    def __init__(self):
        super().__init__()

    def execute(self):
        document = {}
        document['_id'] = self.input['image_id']
        document['type'] = 'image'
        document['image_id'] = self.input['image_id']
        document['status'] = self.input['status']
        document['uploaded_by'] = self.input['public_address']
        document['image_path'] = self.input['image_path']
        document['created_at'] = datetime.timestamp(datetime.now())
        document['updated_at'] = datetime.timestamp(datetime.now())
        document['verified'] = []
        document['cutout_images'] = self.input.get('cutout_images', [])
        document['class'] = self.input['class']
        document['description'] = self.input['description']
        taxonomy_dao.save(document['_id'], document)
        self.successful = True
        return

    def validate_input(self):
        if not self.input:
            self.messages.append("Empty input")
            return False
        if not isinstance(self.input.get('public_address'), str):
            self.messages.append("Empty public_address")
            return False

        if not isinstance(self.input.get('image_id'), str):
            self.messages.append("Empty image_id")
            return False

        if not isinstance(self.input.get('image_path'), str):
            self.messages.append("Empty image_path")
            return False

        if not isinstance(self.input.get('status'), str):
            self.messages.append("Empty status")
            return False

        if not isinstance(self.input.get('class'), str):
            self.messages.append("Empty class")
            return False

        if not isinstance(self.input.get('description'), str):
            self.messages.append("Empty description")
            return False

        return True
