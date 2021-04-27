import os
from locust import HttpUser, task, between
from eth_account import Account
from tests.helper import Helper
from helpers.load_dummy_data import DummyDataLoader
from utils.get_random_string import get_random_string


class UploadTest(HttpUser):
    wait_time = between(1, 2.5)

    def __init__(self, *args, **kwargs):
        super(UploadTest, self).__init__(*args, **kwargs)
        self.token = None
        self.account = None

    def on_start(self):
        self.account = Account.create()
        self.token = Helper.login(self.account.address, self.account.key)

    @task
    def upload_image(self):
        image_name = '{0}.png'.format(get_random_string())
        image_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', image_name)
        DummyDataLoader.generate_image(1024, 1024, image_path)
        headers = {'Authorization': 'Bearer {0}'.format(self.token)}
        url = '/api/v1/upload-file'

        with open(image_path, 'rb') as img:
            files = [
                ('file',
                 (image_path, img, 'image/png'))
            ]
            payload = {'uploaded_by': self.account.address}

            self.client.post(url, headers=headers, data=payload, files=files)

        os.remove(image_path)
