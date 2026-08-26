import os
import json
from locust import HttpUser, task, between
from eth_account import Account
import logging

from dao.static_data_dao import WordTypes
from helpers.login import Login
import random
import sys

from helpers.load_dummy_data import DummyDataLoader
from utils.get_random_string import get_random_string
from commands.staticdata.get_words import GetWordsByTypeCommand


class UploadTest(HttpUser):
    wait_time = between(1, 2.5)

    def __init__(self, *args, **kwargs):
        super(UploadTest, self).__init__(*args, **kwargs)
        self.token = None
        self.account = None
        self.resolutions = None
        self.recommended_words = None
        self.data_directory = None

    def on_start(self):
        self.account = Account.create()

        self.token = Login.register_and_login2(
            self.host, self.account.address, self.account.user_id
        )
        if self.token is None:
            logging.error("Could not get access token")
            sys.exit(1)

        self.resolutions = [
            (614, 874),
            (874, 1240),
            (1240, 1748),
            (1920, 1080),
            (1748, 2480),
        ]

        words_by_type = GetWordsByTypeCommand()
        words_by_type.input = {"type": WordTypes.RECOMMENDED_WORDS.name}

        self.recommended_words = words_by_type.execute()
        if self.recommended_words is None:
            logging.error("No recommended words. Please check static data db.")
            sys.exit(1)

        self.data_directory = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "data"
        )
        if not os.path.exists(self.data_directory):
            os.makedirs(self.data_directory)

    @task(4)
    def upload_image(self):
        url = "/api/v1/upload-file"

        image_name = "{0}.png".format(get_random_string())

        image_path = os.path.join(self.data_directory, image_name)

        x_size, y_size = random.choice(self.resolutions)
        DummyDataLoader.generate_image(x_size, y_size, image_path)
        headers = {"Authorization": "Bearer {0}".format(self.token)}

        with open(image_path, "rb") as img:
            files = [("file", (image_path, img, "image/png"))]
            payload = {"uploaded_by": self.account.address}

            self.client.post(url, headers=headers, data=payload, files=files)

        os.remove(image_path)

    @task(1)
    def verify_image(self):
        headers = {"Authorization": "Bearer {0}".format(self.token)}

        url_metadata = "/api/v1/query-metadata"
        data = {
            "status": "VERIFIABLE",
            "page": 1,
            "fields": ["image_id", "descriptions", "tag_data"],
        }
        response = self.client.post(
            url_metadata, headers=headers, data=json.dumps(data)
        )
        if response.status_code != 200:
            return

        url_base_get_image = "/api/v1/get-image-by-id"

        result = json.loads(response.text)["result"]

        for index, element in enumerate(result):
            image_id = element["image_id"]
            tags = element["tag_data"]
            descriptions = element["descriptions"]

            url_get_image = "{0}?id={1}".format(url_base_get_image, image_id)
            self.client.get(url_get_image, headers=headers, name=url_base_get_image)

            new_tags = []
            new_desc = ""
            if len(tags) < 5 or len(descriptions) < 5:
                new_tags = [random.choice(self.recommended_words)] + [
                    random.choice(self.recommended_words)
                ]
                new_desc = " ".join(
                    [random.choice(self.recommended_words) for i in range(5)]
                )
                self.send_add_metadata_request(image_id, new_tags, new_desc)
            else:
                if len(tags) < 10 or len(descriptions) < 10:
                    new_tags = [random.choice(self.recommended_words)] + [
                        random.choice(self.recommended_words)
                    ]
                    new_desc = " ".join(
                        [random.choice(self.recommended_words) for i in range(10)]
                    )
                up_votes = random.sample(tags, 3)
                down_votes = random.sample(tags, 1)
                desc_downvotes = random.sample(descriptions, 1)
                desc_upvotes = []
                self.send_verify_image_request(
                    image_id,
                    up_votes,
                    down_votes,
                    desc_upvotes,
                    desc_downvotes,
                    new_tags,
                    new_desc,
                )

    def send_verify_image_request(
        self,
        image_id: str,
        tags_upvotes: [str],
        tags_downvotes: [str],
        desc_upvotes: [str],
        desc_down_votes: [str],
        new_tags: [str],
        new_desc: [str],
    ):

        headers = {"Authorization": "Bearer {0}".format(self.token)}
        body = {
            "image_id": image_id,
            "verification": {
                "tags": {"up_votes": tags_upvotes, "down_votes": tags_downvotes},
                "descriptions": {
                    "up_votes": desc_upvotes,
                    "down_votes": desc_down_votes,
                },
            },
            "annotation": {"tags": new_tags, "description": new_desc},
        }

        url_verify = "/api/v1/verify-image"
        self.client.post(url_verify, headers=headers, data=json.dumps(body))

    def send_add_metadata_request(self, image_id: str, tags: [str], desc: str):

        headers = {"Authorization": "Bearer {0}".format(self.token)}
        body = {"image_id": image_id, "tags": tags, "description": desc}

        url_verify = "/api/v1/annotate"
        self.client.post(url_verify, headers=headers, data=json.dumps(body))
