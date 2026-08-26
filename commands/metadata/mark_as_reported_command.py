from commands.base_command import BaseCommand
from dao.metadata_dao import image_metadata_dao


class MarkImageAsReportedCommand(BaseCommand):
    REPORT_THRESHOLD = 3

    def __init__(self):
        super(MarkImageAsReportedCommand, self).__init__()

    def execute(self):
        if not self.validate_input():
            self.successful = False
            return

        image_ids = self.input["photos"]
        image_metadata_dao.marked_as_reported(
            self.input["public_address"],
            image_ids,
            MarkImageAsReportedCommand.REPORT_THRESHOLD,
        )
        self.successful = True
        return

    def validate_input(self):

        if not isinstance(self.input.get("photos"), list):
            self.messages.append("Invalid input body. Expected 'photos' to be a list.")
            return False

        return True
