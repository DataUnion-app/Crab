import os
import json
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
        url = '/api/v1/upload-file'

        image_name = '{0}.png'.format(get_random_string())
        image_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', image_name)
        DummyDataLoader.generate_image(1024, 1024, image_path)
        headers = {'Authorization': 'Bearer {0}'.format(self.token)}

        with open(image_path, 'rb') as img:
            files = [
                ('file',
                 (image_path, img, 'image/png'))
            ]
            payload = {'uploaded_by': self.account.address}

            self.client.post(url, headers=headers, data=payload, files=files)

        os.remove(image_path)

    @task(4)
    def verify_image(self):
        headers = {'Authorization': 'Bearer {0}'.format(self.token)}

        url_metadata = "/api/v1/query-metadata"
        data = {
            "status": "VERIFIABLE",
            "page": 1,
            "fields": ["image_id", "descriptions", "tag_data"]
        }
        response = self.client.post(url_metadata, headers=headers, data=json.dumps(data))
        if response.status_code != 200:
            return

        result = json.loads(response.text)['result']
        if len(result) == 0:
            return

        for i in range(len(result)):
            url_base_get_image = '/api/v1/get-image-by-id'
            image_id = result[i]['image_id']
            url_get_image = "{0}?id={1}".format(url_base_get_image, image_id)
            print("Calling:", url_get_image)
            self.client.get(url_get_image, headers=headers, name=url_base_get_image)

            url_verify = '/api/v1/verify-images'
            payload = json.dumps({'data': [{'image_id': image_id, 'tags': {'up_votes': ['abc'], 'down_votes': ['123']}}]})
            self.client.post(url_verify, headers=headers, data= payload)
