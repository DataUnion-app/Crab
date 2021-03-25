import os
import requests
import json
from config import config
import numpy
from PIL import Image
from eth_account import Account
from helpers.login import Login
from nltk.corpus import words
import nltk
import random
import sys
import datetime

nltk.download('words')


class DummyDataLoader:

    def __init__(self, *args, **kwargs):
        self.url = 'http://localhost:{}'.format(config['application']['port'])
        self.db_host = ''
        self.data_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'helpers', 'data',
                                     'images')

        self.metadata_file = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'helpers',
                                          'data',
                                          'metadata.json')

    def load_data(self, token=None, metadata_file_path=None, data_dir_path=None):
        if not token:
            acct = Account.create()
            login = Login()
        token = login.register_and_login(acct.address, acct.key)
        headers = {'Authorization': 'Bearer {0}'.format(token)}
        with open(metadata_file_path) as metadata_file:
            metadata_content = json.load(metadata_file)
            for metadata in metadata_content['images']:
                file_name = metadata["name"]
                image_path = os.path.join(data_dir_path, file_name)

                image_id = self.upload_image(image_path, file_name, token, acct)

                api_url = self.url + "/api/v1/upload"
                data = {"photo_id": image_id, "timestamp": "", "other": metadata["other"],
                        "tags": metadata["tags"]}
                response = requests.request("POST", api_url, headers=headers, data=json.dumps(data))
                print("Image [{}] metadata upload response: [{}]".format(file_name, response.text.rstrip()))

    def upload_metadata(self, token, account, image_id, metadata):
        headers = {'Authorization': 'Bearer {0}'.format(token)}
        api_url = self.url + "/api/v1/upload"
        start_time = datetime.datetime.now()
        response = requests.request("POST", api_url, headers=headers, data=json.dumps(metadata))
        end_time = datetime.datetime.now()
        delta = int((end_time - start_time).total_seconds() * 1000)
        if response.status_code != 200:
            print("Metadata upload failed for [{}]".format(image_id))
        else:
            print("Image id:[{0}] tagged successfully in [{1}]ms".format(image_id, delta))

    def upload_image(self, file_path, file_name, token, account):
        api_url = self.url + "/api/v1/upload-file"
        payload = {'uploaded_by': account.address}
        headers = {'Authorization': 'Bearer {0}'.format(token)}

        if not os.path.exists(file_path):
            print("Image [{}] does not exist".format(file_path))
            return None

        with open(file_path, 'rb') as img:
            files = [
                ('file',
                 (file_name, img, 'image/png'))
            ]

            start_time = datetime.datetime.now()
            response = requests.request("POST", api_url, headers=headers, data=payload, files=files)
            end_time = datetime.datetime.now()
            delta = end_time - start_time
            if response.status_code == 200:
                data = json.loads(response.text)
                print("Image [{0}] uploaded with id [{1}] successfully in [{2}]ms".format(file_path, data["id"], int(
                    delta.total_seconds() * 1000)))
                return data["id"]
            else:
                print("Image upload failed with response code [{}]".format(response.status_code))
                return None

    def generate_image(self, x_size, y_size, path):
        image_array = numpy.random.rand(x_size, y_size, 3) * 255
        im = Image.fromarray(image_array.astype('uint8')).convert('RGBA')
        im.save(path)

    def generate_random_images(self, x_size=250, y_size=250, count=1):
        dir_path = os.path.join(self.data_dir, 'random')
        for i in range(count):
            self.generate_image(x_size, y_size, os.path.join(dir_path, '{0}.png'.format(i)))

    def generate_dummy_data(self, count):
        self.generate_random_images(250, 250, count)
        self.generate_dummy_metadata(count)

    def generate_dummy_metadata(self, count):
        data = []
        for i in range(count):
            n = random.randint(1, 10)

            rand_words = random.sample(words.words(), n)

            data.append({
                "name": "{0}.png".format(i),
                "tags": rand_words
            })

        meta_data = {"images": data}
        meta_data_path = os.path.join(self.data_dir, 'random', 'metadata.json')

        with open(meta_data_path, 'w') as fp:
            json.dump(meta_data, fp)

    def load_random_data(self, count=10, accounts=1):
        self.generate_random_images(100, 100, count)
        print("Random images generated")
        self.generate_dummy_metadata(count)
        print("Random metadata generated")
        metadata_file_path = os.path.join(self.data_dir, 'random', 'metadata.json')
        data_dir_path = os.path.join(self.data_dir, 'random')
        self.load_data(metadata_file_path=metadata_file_path, data_dir_path=data_dir_path)
        print("Finished loading dummy data")

    def load_random_data2(self, count=10, accounts=1, x_size=100, y_size=100):

        login = Login()
        accts = [Account.create() for i in range(accounts)]
        print("Getting login tokens for [{}] accounts".format(accounts))
        tokens = [login.register_and_login(acct.address, acct.key) for acct in accts]
        for acct in accts:
            print("Public address:{0} key:{1}".format(acct.address, acct.key.hex()))

        dir_path = os.path.join(self.data_dir, 'random')
        if not os.path.exists(dir_path):
            os.mkdir(dir_path)

        image_ids = []

        for i in range(count):
            idx = random.randint(0, len(accts) - 1)
            file_path = os.path.join(dir_path, '{0}.png'.format(i))
            self.generate_image(x_size, y_size, file_path)
            image_id = self.upload_image(file_path, '{0}.png'.format(i), tokens[idx], accts[idx])
            os.remove(file_path)

            if image_id is not None:
                image_ids.append(image_id)
                idx2 = random.randint(0, len(accts) - 1)
                image_ids.append(image_id)
                self.upload_metadata(tokens[idx2], accts[idx2], image_id, self.get_dummy_metadata(image_id))
        print("Finished loading dummy data")
        return image_ids

    def load_random_data3(self, account=None, token=None, count=10, x_size=100, y_size=100):
        if token is None or account is None:
            print("Token or account is None")
            return

        dir_path = os.path.join(self.data_dir, 'random')
        if not os.path.exists(dir_path):
            os.mkdir(dir_path)

        image_ids = []

        for i in range(count):
            file_path = os.path.join(dir_path, '{0}.png'.format(i))
            self.generate_image(x_size, y_size, file_path)
            image_id = self.upload_image(file_path, '{0}.png'.format(i), token, account)
            os.remove(file_path)

            if image_id is not None:
                image_ids.append(image_id)
                self.upload_metadata(token, account, image_id, self.get_dummy_metadata(image_id))
        print("Finished loading dummy data")
        return image_ids

        return image_ids

    def get_dummy_metadata(self, image_id):
        n = random.randint(1, 10)

        rand_words = random.sample(words.words(), n)
        return {"photo_id": image_id, "timestamp": "", "tags": rand_words}


if __name__ == '__main__':
    if len(sys.argv) < 3:
        print("Usage: python -m helpers.load_dummy_data <images> <accounts> <x_size> <y_size>")
        exit(-1)

    images = int(sys.argv[1])
    accounts = int(sys.argv[2])

    x_size = 1024
    y_size = 1024

    if len(sys.argv) == 5:
        x_size = int(sys.argv[3])
        y_size = int(sys.argv[4])

    d = DummyDataLoader()
    d.load_random_data2(count=images, accounts=accounts, x_size=x_size, y_size=y_size)
