import argparse
import os
import logging
import getpass
import sys
import requests

from commands.metadata.create_new_entity.create_brainstem_entity import EntitySubType
from helpers.input_validators.address import ValidateAddress
from models.metadata.metadata_models import Source

logging.basicConfig()
logging.getLogger().setLevel(logging.INFO)

from helpers.login import Login

parser = argparse.ArgumentParser()
parser.add_argument("--address", help="Wallet address", required=True, action=ValidateAddress)
parser.add_argument('--source', type=str, required=False, default=Source.default)
parser.add_argument('--file_type', type=str, required=False)
parser.add_argument('--directory', type=str, required=False)


def get_file_paths(directory):
    only_files = [(f, os.path.join(directory, f)) for f in os.listdir(directory) if
                  os.path.isfile(os.path.join(directory, f))]
    return only_files


def get_token(public_address: str, private_key: str, source: Source) -> str:
    login = Login()
    exists, nonce = login.user_exists(public_address)

    if exists:
        token = login.login(public_address, private_key, source).get('access_token')
    else:
        token = login.register_and_login(public_address, private_key, source)
    if token is None:
        logging.error("Access token is None")
        sys.exit(-1)
    return token


def load_file(file_name, file_path, file_type, access_token):
    url = "http://localhost:8080/api/v1/upload-file"

    payload = {'file-type': file_type}
    files = [('file', (file_name, open(file_path, 'rb'), 'text/plain'))]
    headers = {
        'Authorization': f'Bearer {access_token}'
    }

    response = requests.request("POST", url, headers=headers, data=payload, files=files)
    logging.info("Uploaded file [%s] with response code [%s]", file_path, response.status_code)
    if response.status_code != 200:
        logging.info("Response text [%s]", response.text)


if __name__ == "__main__":

    args = parser.parse_args()
    acct_address = args.address
    source = args.source
    file_type = args.file_type
    directory = args.directory

    acct_key = getpass.getpass(prompt="Private key:")

    if not os.path.isdir(directory):
        logging.error("Not a directory: [%s]", directory)
        sys.exit(-1)
    # path = os.path.join("staging", "brainstem", "files")

    access_token = get_token(acct_address, acct_key, source)
    logging.info("Access token generated")

    logging.info("Uploading files of type [%s]", file_type)

    files = get_file_paths(directory)
    for file_path in files:
        # file_path[0] = file name
        # file_path[1] = absolute file path
        load_file(file_path[0], file_path[1], file_type, access_token)
