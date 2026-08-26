from config import config
from commands.base_command import BaseCommand
import requests


class UploadIpfsCommand(BaseCommand):
    IPFS_API_KEY = config["ipfs"]["api_key"]
    IPFS_API_SECRET = config["ipfs"]["api_secret"]
    IPFS_ENDPOINT = config["ipfs"]["endpoint"]

    def __init__(self, file_path: str):
        super().__init__()
        self.file_path = file_path

    def execute(self):
        try:
            f = open(self.file_path, "rb")
            files = {
                'file': f.read()
            }

            ### ADD FILE TO IPFS AND SAVE THE HASH ###
            response = requests.post(self.IPFS_ENDPOINT + '/api/v0/add', files=files, auth=(self.IPFS_API_KEY, self.IPFS_API_SECRET))
            hash = response.text.split(",")[1].split(":")[1].replace('"','')

            self.successful = True
            return {
                "hash": hash,
                "url": "https://ipfs.io/ipfs/{}".format(hash)
            }
        except Exception as e:
            print(e)
            self.messages.append(e)
            self.successful = False