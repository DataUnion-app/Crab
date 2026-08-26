import datetime
import json
import logging
import time

import pandas as pd

import commands.dataunions.wedatanation.build_avatar as avatar
import commands.dataunions.wedatanation.data_utils as du
from commands.base_command import BaseCommand
from commands.dataunions.wedatanation.fetch_avatar import FetchUserAvatar
from dao.metadata_dao import image_metadata_dao
from dao.users_dao import user_dao
from models.User import AvatarGenerationStatus


class BuildUserAvatarCommand(BaseCommand):
    def __init__(self, public_address: str, task_id: str = None, force_recreate: bool = False):
        super(BuildUserAvatarCommand, self).__init__(public_address)
        self.task_id = task_id
        self.force_recreate = force_recreate

    def execute(self):
        logging.info("Executing BuildUserAvatar for user avatar for [%s]", self.public_address)
        star_time = time.time()
        logging.info("Starting to build user avatar for [%s]", self.public_address)

        user = user_dao.get_by_public_address(self.public_address)["result"][0]

        if user.get("avatar") is None:
            user["avatar"] = {}
            user["created_at"] = datetime.datetime.utcnow().isoformat()
            user["avatar"]["status"] = AvatarGenerationStatus.creating

        if user["avatar"].get("staging") is not None and self.force_recreate is False:
            logging.info("Not allowing user [%s] to generate avatar again as another task [%s] already running",
                         self.public_address, user["avatar"].get("staging"))
            self.successful = False
            self.messages.append("Already avatar generation task running")
            return

        user["avatar"]["staging"] = {
            "task_id": self.task_id,
            "status": AvatarGenerationStatus.creating
        }

        # user["avatar"]["status"] = AvatarGenerationStatus.creating
        current_time = datetime.datetime.utcnow().isoformat()
        user["avatar"]["updated_at"] = current_time
        user["avatar"]["started_at"] = current_time

        user_dao.update_doc(user["_id"], user)

        final = du.unified_profile_data(self.public_address, image_metadata_dao)
        df = pd.DataFrame(final)

        user_avatar, df_similarities_an, df_similarities_att, df_similarities_itm = avatar.compute_profile(df,
                                                                                                           self.public_address)
        result = {
            'animals': json.loads(df_similarities_an.to_json(orient="records")),
            'attributes': json.loads(df_similarities_att.to_json(orient="records")),
            'items': json.loads(df_similarities_itm.to_json(orient="records"))
        }
        end_time = time.time()
        computation_time = f'{round((end_time - star_time) / 60, 1)} minutes'

        user = user_dao.get_by_public_address(self.public_address)["result"][0]

        current_time = datetime.datetime.utcnow().isoformat()
        user["avatar"]["updated_at"] = current_time
        user["avatar"]["ended_at"] = current_time
        user["avatar"]["result"] = result
        user["avatar"]["user_avatar"] = user_avatar["avatar"]
        user["avatar"]["status"] = AvatarGenerationStatus.generated

        user["avatar"]["task_id"] = user["avatar"]["staging"]["task_id"]
        user["avatar"]["staging"] = None

        user_dao.update_doc(user["_id"], user)

        logging.info("Build avatar result: %s", user_avatar)
        logging.info("Finished executing BuildUserAvatar for user avatar for [%s] in [%s]", self.public_address,
                     computation_time)
        self.successful = True
        return user_avatar


if __name__ == "__main__":
    public_address = "0x" + "1" * 40
    build_avatar_cmd = BuildUserAvatarCommand(public_address)
    result = build_avatar_cmd.execute()

    f = FetchUserAvatar(public_address, result['avatar'], True)
    result = f.execute()

    if not build_avatar_cmd.successful:
        raise ValueError(f'Error executing BuildUserAvatarCommand for [{public_address}]')
    logging.info("result", result)
