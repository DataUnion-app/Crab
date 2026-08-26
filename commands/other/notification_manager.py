from commands.base_command import BaseCommand
from dao.others_dao import others_db


class GetPendingNotifications(BaseCommand):
    def __init__(self, public_address: str, mark_as_read: bool = True):
        super(GetPendingNotifications, self).__init__(public_address)
        self.mark_as_read = mark_as_read

    def execute(self):
        result = others_db.get_notifications_for_user(self.public_address)

        if self.mark_as_read is True:
            notification_ids = [p["id"] for p in result]
            others_db.mark_notifications_as_read(self.public_address, notification_ids)
        self.successful = True
        return result
