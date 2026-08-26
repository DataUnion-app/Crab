from commands.base_command import BaseCommand
from commands.dataunions.wedatanation.fetch_avatar import FetchUserAvatar
from dao.users_dao import user_dao
import requests
from urllib.parse import unquote
from task_handler.worker import celery

# from celery.task.control import revoke

from models.User import AvatarGenerationStatus


class ReserveUserAvatarCommand(FetchUserAvatar):

    def __init__(self, public_address: str, avatar_url: str):
        super(ReserveUserAvatarCommand, self).__init__(public_address, [], False)
        self.avatar_url = avatar_url

    def reserve_avatar(self):
        response = requests.post(
            f"{self.backend_url}/wedatanation/avatar/reserve",
            json=
            {
                "images": [self.avatar_url],
                "user_id": "dataunion-" + self.public_address,
                "reserved": True
            }
            ,
            headers={"Authorization": f"Bearer {self.get_token()}"},
        )
        return response.status_code == 200, response.json() if response.status_code == 200 else None

    def execute(self):
        user = user_dao.get_by_public_address(self.public_address)["result"][0]

        if unquote(self.avatar_url) not in user['avatar_result']['result']['images']:
            self.successful = False
            self.messages.append(f"User profile does not have given image url [{self.avatar_url}]")
            return

        if user.get('reserved_avatars') is not None and self.avatar_url in user.get('reserved_avatars'):
            self.successful = False
            self.messages.append("Avatar already reserved")
            return

        success, result = self.reserve_avatar()
        if success:
            if user.get('reserved_avatars') is None:
                user['reserved_avatars'] = []

            user['reserved_avatars'].append(self.avatar_url)
            user_dao.update_doc(user["_id"], user)
            self.successful = True
            return result
        else:
            self.successful = False
            self.messages.append("Avatar reservation failed")
            return


class StopAvatarGenerationTask(BaseCommand):
    def __init__(self, public_address: str):
        super(StopAvatarGenerationTask, self).__init__(public_address)

    def execute(self):
        user_object = user_dao.get_by_public_address(self.public_address)["result"][0]
        if user_object.get("avatar") is None or user_object["avatar"].get("staging") is None:
            # No task running. Nothing to stop. so return
            self.successful = False
            self.messages.append("No avatar generation task running")
            return

        task_id = user_object["avatar"]["staging"]["task_id"]
        celery.control.revoke(task_id, terminate=True)

        user_object["avatar"]["staging"] = None
        user_object["avatar"]["status"] = AvatarGenerationStatus.stopped

        user_dao.update_doc(user_object["_id"], user_object)

        self.successful = True
        return
