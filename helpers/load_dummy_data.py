import os
import requests
import json
from config import config
from eth_account import Account
from helpers.login import Login


class DummyDataLoader:

    def __init__(self, *args, **kwargs):
        self.url = 'http://localhost:{}'.format(config['application']['port'])
        self.db_host = ''
        self.data_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'helpers', 'data',
                                     'images')

        self.metadata_file = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'helpers',
                                          'data',
                                          'metadata.json')

    def load_data(self, token=None):
        if not token:
            acct = Account.create()
            login = Login()
        token = login.register_and_login(acct.address, acct.key)
        headers = {'Authorization': 'Bearer {0}'.format(token)}
        with open(self.metadata_file) as metadata_file:
            metadata_content = json.load(metadata_file)
            for metadata in metadata_content['images']:

                api_url = self.url + "/api/v1/upload-file"
                payload = {'uploaded_by': acct.address}

                file_name = metadata["name"]
                image_path = os.path.join(self.data_dir, file_name)

                if not os.path.exists(image_path):
                    print("Image [{}] does not exist".format(image_path))
                    continue

                with open(image_path, 'rb') as img:
                    files = [
                        ('file',
                         (file_name, img, 'image/png'))
                    ]
                    print("Uploading file {}".format(file_name))
                    response = requests.request("POST", api_url, headers=headers, data=payload, files=files)
                    print("Image [{}] upload response: [{}]".format(file_name, response.text.rstrip()))
                    if response.status_code == 200:
                        data = json.loads(response.text)

                        image_id = data["id"]

                        api_url = self.url + "/api/v1/upload"
                        data = {"photo_id": image_id, "timestamp": "", "other": metadata["other"],
                                "tags": metadata["tags"]}
                        response = requests.request("POST", api_url, headers=headers, data=json.dumps(data))
                        print("Image [{}] metadata upload response: [{}]".format(file_name, response.text.rstrip()))


if __name__ == '__main__':
    d = DummyDataLoader()
    d.load_data()
