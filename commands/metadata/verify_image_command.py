import unicodedata

from commands.bounty.bounty_commands import UpdateBountyProgress
from dao.metadata_dao import image_metadata_dao
from commands.base_command import BaseCommand
from dao.missions_dao import missions_dao
from dao.static_data_dao import WordTypes, static_data_dao


class VerifyImageCommand(BaseCommand):
    MAX_DESCRIPTION_LENGTH = 2000
    MAX_TAG_LENGTH = 200

    def __init__(self, public_address: str, mission_id: str):
        super().__init__(public_address=public_address)
        self.image_metadata_dao = image_metadata_dao
        self.static_data_dao = static_data_dao
        self.mission_id = mission_id

    def execute(self):
        if self.mission_id:
            # Check if mission is assigned to user
            user_mission_information = missions_dao.get_mission_details_for_user(self.public_address, self.mission_id)
            if not user_mission_information:
                self.successful = False
                self.messages.append("Invalid mission id")
                return

            image_id = self.input.get("image_id")
            if image_id not in user_mission_information["entity_ids"]:
                self.successful = False
                self.messages.append(
                    f"Submission not permitted for image id [{image_id}] for mission [{self.mission_id}]")
                return

        if not self.validate_input():
            self.successful = False
            self.messages.append("Invalid input.")
            return

        self.clean_input()

        if self.has_banned_words():
            self.messages.append("Tags contains banned word(s)")
            self.successful = False
            return

        if not self.has_valid_tag_length():
            self.successful = False
            return

        verification_id = self.image_metadata_dao.mark_image_as_verified(
            self.input["image_id"], self.input["data"], self.input["public_address"]
        )

        if verification_id:
            self.image_metadata_dao.move_to_verified_if_possible(self.input["image_id"])
            self.successful = True
        else:
            self.messages.append("Image could not be verified")
            self.successful = False
            return

        if self.mission_id:
            missions_dao.update_progress(self.mission_id, verification_ids=[verification_id])
            bounty_id = missions_dao.get_mission_details_by_id(mission_id=self.mission_id)['bounty_id']
            UpdateBountyProgress(bounty_id=bounty_id, entity_ids=[verification_id]).execute()

    def validate_input(self):
        if not self.input:
            self.messages.append("Empty input body.")
            return False

        if not self.input.get("data"):
            self.messages.append('"data" is empty.')
            return False

        if not isinstance(self.input.get("public_address"), str):
            self.messages.append('"public_address" is not a string.')
            return False

        if not isinstance(self.input.get("image_id"), str):
            self.messages.append('"image_id" is not a string.')
            return False

        return True

    def clean_input(self):
        pass

    @staticmethod
    def remove_control_characters(tag):
        return "".join(ch for ch in tag if unicodedata.category(ch)[0] != "C")

    def has_banned_words(self):
        banned_words = self.static_data_dao.get_words_by_type(
            WordTypes.BANNED_WORDS.name
        )
        tags_lower_case = []
        tags_lower_case = tags_lower_case + list(
            map(lambda x: x.lower(), self.input["data"]["tags"]["up_votes"])
        )
        tags_lower_case = tags_lower_case + list(
            map(lambda x: x.lower(), self.input["data"]["tags"]["down_votes"])
        )
        tags_lower_case = tags_lower_case + list(
            map(lambda x: x.lower(), self.input["data"]["descriptions"]["up_votes"])
        )
        tags_lower_case = tags_lower_case + list(
            map(lambda x: x.lower(), self.input["data"]["descriptions"]["down_votes"])
        )
        banned_words_in_input = list(set(tags_lower_case) & set(banned_words))
        if len(banned_words_in_input) > 0:
            return True
        return False

    def has_valid_tag_length(self):
        tags = (
                self.input["data"]["tags"]["up_votes"]
                + self.input["data"]["tags"]["down_votes"]
        )
        all_tags_in_limit = all(
            [len(tag) <= VerifyImageCommand.MAX_TAG_LENGTH for tag in tags]
        )

        if not all_tags_in_limit:
            self.messages.append(
                "Length of tag(s) exceeds limit of [{0}] characters.".format(
                    VerifyImageCommand.MAX_TAG_LENGTH
                )
            )
            return False

        descriptions = (
                self.input["data"]["descriptions"]["up_votes"]
                + self.input["data"]["descriptions"]["down_votes"]
        )
        all_descriptions_in_limit = all(
            [
                len(description) <= VerifyImageCommand.MAX_DESCRIPTION_LENGTH
                for description in descriptions
            ]
        )

        if not all_descriptions_in_limit:
            self.messages.append(
                "Length of description(s) exceeds limit of [{0}] characters.".format(
                    VerifyImageCommand.MAX_DESCRIPTION_LENGTH
                )
            )
            return False

        return True

    @property
    def is_valid(self):
        pass
