import argparse
import logging
import sys

from commands.dataunions.wedatanation import SaveTokenBalancesByUser
from helpers.input_validators.address import ValidateAddress
from models.metadata.metadata_models import Network

logging.basicConfig(stream=sys.stdout, level=logging.INFO)

parser = argparse.ArgumentParser()
parser.add_argument("-a", "--address", help="Wallet address", required=True, action=ValidateAddress)
parser.add_argument("-n", "--network", help="Network name", required=True, action=ValidateAddress)

if __name__ == "__main__":
    args = parser.parse_args()
    file = args.file
    public_address = args.address
    network = Network(args.network)

    c = SaveTokenBalancesByUser(public_address, public_address, network, update_database=True)
    c.execute()
    assert c.successful
