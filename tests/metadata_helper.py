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
