from eth_account import Account

from commands.metadata.add_new_metadata_command import AddNewMetadataCommand
from commands.metadata.verify_image_command import VerifyImageCommand


class MetadataHelper:

    @staticmethod
    def mark_as_verified(image_ids, up_votes, down_votes):
        acct = Account.create()
        verify_image_command = VerifyImageCommand()
        data = [{'image_id': image_id, 'tags': {'up_votes': up_votes, 'down_votes': down_votes}} for image_id in
                image_ids]
        verify_image_command.input = {
            'public_address': acct.address,
            'data': data
        }

        verify_image_command.execute()

    @staticmethod
    def add_metadata(image_id, tags):
        acct = Account.create()
        add_new_metadata_command1 = AddNewMetadataCommand()
        add_new_metadata_command1.input = {
            'public_address': acct.address,
            'tags': tags,
            'photo_id': image_id
        }

        add_new_metadata_command1.execute()

    @staticmethod
    def mark_images_as_verified(public_address, image_ids, tag_up_votes: list[str], tag_down_votes: list[str],
                                desc_up_votes: list[str],
                                desc_down_votes: list[str]):
        if not public_address:
            acct = Account.create()
            public_address = acct.address
        verify_image_command = VerifyImageCommand()
        data = [{'image_id': image_id, 'tags': {'up_votes': tag_up_votes, 'down_votes': tag_down_votes},
                 'descriptions': {'up_votes': desc_up_votes, 'down_votes': desc_down_votes}} for image_id in
                image_ids]
        verify_image_command.input = {
            'public_address': public_address,
            'data': data
        }

        verify_image_command.execute()
