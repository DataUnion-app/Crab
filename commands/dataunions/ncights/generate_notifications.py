import logging
import sys
from logging.handlers import TimedRotatingFileHandler

from commands.base_command import BaseCommand
from commands.dataunions.ncights.rank_users_command import RankUserCommand
from config import config
from dao.others_dao import others_db, NotificationType
from datetime import datetime
from dao.users_dao import user_dao
import os

from utils.get_project_dir import get_project_root

log_filename = os.path.join(get_project_root(), 'logs', "ncight_notification_task.log")
handler = TimedRotatingFileHandler(filename=log_filename, when="D", interval=1)
logging.basicConfig(
    format="%(asctime)s %(levelname)s:%(message)s",
    level=config["logging"].getint("level"),
    handlers=[handler],
)


def my_handler(type, value, tb):
    logging.exception("Uncaught exception: {0}".format(str(value)))


# Install exception handler
sys.excepthook = my_handler


class GenerateNcightNotifications(BaseCommand):
    def __init__(self, check_new_users: bool = True, user_ranks: bool = True):
        super(GenerateNcightNotifications, self).__init__()

        self.doc_id = "task-ncight_notifications"
        self.check_new_users = check_new_users
        self.user_ranks = user_ranks

        exists = others_db.check_if_exists(self.doc_id)
        if not exists:
            self.document = {"created_at": datetime.utcnow().isoformat()}
            result = user_dao.get_all()["result"]
            self.document["users"] = {
                "count": len(result),
                "addresses": [u["public_address"] for u in result]
            }
            self.document["user_ranks"] = {}

            others_db.save(self.doc_id, self.document)

    def execute(self):
        logging.debug("Executing notification generation task")
        self.document = others_db.get_doc_by_id(self.doc_id)

        if self.check_new_users:
            logging.info("Checking for new users")

            self.check_for_new_users()

        if self.user_ranks:
            logging.info("Generating user ranks")
            self.check_for_rank_changes()

        self.document["last_execution_time"] = datetime.utcnow().isoformat()
        others_db.update_doc(self.doc_id, self.document)

        self.successful = True
        logging.info("Finished generating notifications")

    def check_for_new_users(self):
        new_count = user_dao.get_users_count()["count"]
        users = self.document["users"]
        if users["count"] < new_count:
            # Some new user has registered
            all_users = user_dao.get_all()["result"]
            new_addresses = [u["public_address"] for u in all_users]

            old_addresses = self.document["users"]["addresses"]
            delta = set(new_addresses).difference(set(old_addresses))
            delta = list(delta)
            for d in delta:
                new_user = next(u for u in all_users if u["public_address"] == d)
                referral_id = new_user.get("referred_by")
                if referral_id is not None:
                    referrer = next(u for u in all_users if u.get("referral_id") == referral_id)
                    if referrer is not None:
                        # Generate notification for user whose referral id was used
                        others_db.generate_notification_for_user(referrer["public_address"],
                                                                 NotificationType.referral_used, {
                                                                     "title": "New referral !",
                                                                     "message": "A new user joined with your referral id!"
                                                                 })

            self.document["users"]["count"] = new_count
            self.document["users"]["addresses"] = new_addresses

        return new_count

    def check_for_rank_changes(self):
        old_ranks = self.document.get("user_ranks", {})
        c = RankUserCommand()
        result = c.execute()
        new_ranks = {}
        for index, r in enumerate(result):
            new_ranks[r['address']] = index + 1
            old_user_rank = old_ranks.get(r['address'], -1)

            if old_user_rank != -1 and (index + 1) != old_user_rank:
                others_db.generate_or_replace_notification_for_user_by_type(r['address'], NotificationType.rank_updated,
                                                                            {
                                                                                "title": "Rank update !",
                                                                                "message": "",
                                                                                "old-rank": old_user_rank,
                                                                                'new-rank': index + 1
                                                                            })
        self.document['user_ranks'] = new_ranks


if __name__ == "__main__":
    c = GenerateNcightNotifications(check_new_users=True)
    c.execute()
    assert c.successful
