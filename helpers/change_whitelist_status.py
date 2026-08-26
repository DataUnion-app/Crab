import argparse

from commands.whitelist.whitelist_command import WhitelistCommand

parser = argparse.ArgumentParser()
parser.add_argument("-r", "--address",
                    help="A wallet to add/remove to the whitelist.")
parser.add_argument('--add', dest='add_whitelist', action='store_true')
parser.add_argument('--remove', dest='add_whitelist', action='store_false')


def update_whitelist(address, update_type=True):
    """
    This function is to add/remove a wallet address to/in the whitelist.

    :param address: a wallet address to add/remove to/from the whitelist
    :param update_type: Boolean value to determine whether to add or remove an address
    """
    if not address:
        print('Please make sure the address is not empty!')
        return

    whitelist_handler = WhitelistCommand()
    whitelists = whitelist_handler.get_latest_whitelist()

    if update_type:
        whitelists.append(address)
    else:
        if not whitelists:
            print('Whitelist is empty, so nothing to remove')
            return
        if address not in whitelists:
            print(f'The {address} does not exist in the current whitelist address.')
            return
        whitelists.remove(address)

    whitelist_handler.prepare_whitelist(whitelists)


if __name__ == "__main__":
    args = parser.parse_args()
    update_whitelist(args.address, args.add_whitelist)
