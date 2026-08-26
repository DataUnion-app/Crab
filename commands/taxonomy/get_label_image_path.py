from commands.base_command import BaseCommand
from config import config
import os


class GetLabelImagePathCommand(BaseCommand):
    def __init__(self):
        super().__init__()

    def execute(self):

        if not self.validate_input():
            self.successful = False
            return

        label_id = self.input["label_id"]

        label_dir = config["taxonomy"]["labels_folder"]
        label_path = os.path.join(label_dir, label_id + ".png")
        if not os.path.isfile(label_path):
            self.successful = False
            self.messages.append("Label image not found")
            return

        self.successful = True
        return label_path

    def validate_input(self):
        if not self.input:
            self.messages.append("Missing input")
            return False

        if not isinstance(self.input.get("label_id"), str):
            self.messages.append("Missing label_id")
            return False

        return True
