import argparse
import logging
import sys

from commands.dataunions.wedatanation import AddUserFacebookDataFromZipFile
from helpers.input_validators.address import ValidateAddress

logging.basicConfig(stream=sys.stdout, level=logging.INFO)

parser = argparse.ArgumentParser()
parser.add_argument("-a", "--address", help="Wallet address", required=True, action=ValidateAddress)
parser.add_argument('--file', type=str, required=True)

if __name__ == "__main__":
    args = parser.parse_args()
    file = args.file
    public_address = args.address

    try:
        c = AddUserFacebookDataFromZipFile(public_address, file)
        result = c.execute()
        if not c.successful:
            logging.error(f"Failed to load json file: {c.messages}")
            sys.exit(-1)
        else:
            logging.info(f"Data saved in database. Document id [{result}]")
    except Exception as e:
        logging.exception("Failed to save to database", exc_info=e)
