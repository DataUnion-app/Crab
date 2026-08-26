import unicodedata

from commands.bounty.bounty_commands import UpdateBountyProgress
from dao.metadata_dao import image_metadata_dao
from dao.missions_dao import missions_dao
from dao.static_data_dao import static_data_dao, WordTypes
from commands.base_command import BaseCommand
from models.missions import MissionStatus


class AddNewMetadataCommand(BaseCommand):
    MAX_DESCRIPTION_LENGTH = 2000
    MAX_TAG_LENGTH = 200

    def __init__(self, public_address: str, mission_id: str):
        super().__init__(public_address=public_address)
        self.image_metadata_dao = image_metadata_dao
        self.staticdata_dao = static_data_dao
        self.mission_id = mission_id

    def execute(self):
        self.clean_input()

        if self.mission_id:
            # Check if mission is assigned to user
            user_mission_information = missions_dao.get_mission_details_for_user(self.public_address, self.mission_id)
            if not user_mission_information:
                self.successful = False
                self.messages.append("Invalid mission id")
                return

            # Check if mission is in progress
            if user_mission_information['status'] not in [MissionStatus.IN_PROGRESS, MissionStatus.READY_TO_START]:
                self.successful = False
                self.messages.append(f"Invalid mission status [{user_mission_information['status']}]")
                return

        if not self.image_metadata_dao.exists(self.input["image_id"]):
            self.successful = False
            self.messages.append(f"Image with id [{self.input['image_id']}] does not exist.")
            return

        if not self.validate_input():
            self.successful = False
            return {"status": "failed"}

        banned_words = self.staticdata_dao.get_words_by_type(
            WordTypes.BANNED_WORDS.name
        )

        tags_lower_case = map(lambda x: x.lower(), self.input["tags"])

        banned_words_in_input = list(set(tags_lower_case) & set(banned_words))
        if len(banned_words_in_input) > 0:
            self.messages.append(
                "Tags contains banned words {}".format(banned_words_in_input)
            )
            self.successful = False
            return {"status": "failed"}

        annotation_ids = []

        if self.input.get("tags"):
            annotation_id = self.image_metadata_dao.add_tags_for_image(
                self.input["public_address"], self.input["image_id"], self.input["tags"]
            )

            annotation_ids.append(annotation_id)

        if self.input.get("description"):
            annotation_id = self.image_metadata_dao.add_description_for_image(
                self.input["public_address"],
                self.input["image_id"],
                self.input["description"],
            )
            annotation_ids.append(annotation_id)

        if self.mission_id and len(annotation_ids) >= 1:
            missions_dao.update_progress(self.mission_id, annotation_ids=annotation_ids)
            bounty_id = missions_dao.get_mission_details_by_id(mission_id=self.mission_id)['bounty_id']
            UpdateBountyProgress(bounty_id=bounty_id, entity_ids=annotation_ids).execute()

        self.successful = True
        return {"status": "success"}

    def clean_input(self):
        self.input["tags"] = list(map(str.strip, self.input.get("tags")))
        self.input["tags"] = list(
            map(AddNewMetadataCommand.remove_control_characters, self.input.get("tags"))
        )

    @staticmethod
    def remove_control_characters(tag):
        return "".join(ch for ch in tag if unicodedata.category(ch)[0] != "C")

    def validate_input(self):
        if not isinstance(self.input.get("image_id"), str):
            self.messages.append("Missing parameter 'image_id'")
            return False

        if self.input.get("description") is not None:
            if (
                    len(self.input.get("description"))
                    > AddNewMetadataCommand.MAX_DESCRIPTION_LENGTH
            ):
                self.messages.append(
                    "Length of description exceeds limit of [{0}] characters.".format(
                        AddNewMetadataCommand.MAX_DESCRIPTION_LENGTH
                    )
                )
                return False

        all_tags_in_limit = all(
            [
                len(tag) <= AddNewMetadataCommand.MAX_TAG_LENGTH
                for tag in self.input.get("tags")
            ]
        )

        if not all_tags_in_limit:
            self.messages.append(
                "Length of tag(s) exceeds limit of [{0}] characters.".format(
                    AddNewMetadataCommand.MAX_TAG_LENGTH
                )
            )
            return False
        return True

    @property
    def is_valid(self):
        pass
