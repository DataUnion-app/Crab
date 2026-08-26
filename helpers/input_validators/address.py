import argparse

from web3 import Web3


class ValidateAddress(argparse.Action):
    def __call__(self, parser, namespace, values, option_string=None):
        if not Web3.isAddress(values):
            parser.error(f"Please enter a valid address. Got: {values}")
        setattr(namespace, self.dest, values)
