import os
import requests
import json

from commands.metadata.add_new_metadata_command import AddNewMetadataCommand
from config import config
import numpy
from PIL import Image
from eth_account import Account

from dao.static_data_dao import WordTypes
from helpers.login import Login
import random
import sys
import datetime
from commands.metadata.verify_image_command import VerifyImageCommand
from commands.staticdata.get_words import GetWordsByTypeCommand


class DummyDataLoader:
    def __init__(self, *args, **kwargs):
        self.url = "http://localhost:{}".format(config["application"]["port"])
        self.db_host = ""
        self.data_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "helpers",
            "data",
            "images",
        )

        self.metadata_file = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "helpers",
            "data",
            "metadata.json",
        )

        get_words = GetWordsByTypeCommand()
        get_words.input = {"type": WordTypes.RECOMMENDED_WORDS.name}
        self.words = get_words.execute()

    def load_data(self, token=None, metadata_file_path=None, data_dir_path=None):
        if not token:
            acct = Account.create()
            login = Login()
        token = login.register_and_login(acct.address, acct.user_id)
        headers = {"Authorization": "Bearer {0}".format(token)}
        with open(metadata_file_path) as metadata_file:
            metadata_content = json.load(metadata_file)
            for metadata in metadata_content["images"]:
                file_name = metadata["name"]
                image_path = os.path.join(data_dir_path, file_name)

                image_id = self.upload_image(image_path, file_name, token)

                api_url = self.url + "/api/v1/annotate"
                data = {"image_id": image_id, "tags": metadata["tags"]}
                response = requests.request(
                    "POST", api_url, headers=headers, data=json.dumps(data)
                )
                print(
                    "Image [{}] metadata upload response: [{}]".format(
                        file_name, response.text.rstrip()
                    )
                )

    def upload_metadata(self, token, account, image_id, metadata):
        headers = {"Authorization": "Bearer {0}".format(token)}
        api_url = self.url + "/api/v1/annotate"
        start_time = datetime.datetime.now()
        response = requests.request(
            "POST", api_url, headers=headers, data=json.dumps(metadata)
        )
        end_time = datetime.datetime.now()
        delta = int((end_time - start_time).total_seconds() * 1000)
        if response.status_code != 200:
            print("Metadata upload failed for [{}]".format(image_id))
        else:
            print(
                "Image id:[{0}] tagged successfully in [{1}]ms".format(image_id, delta)
            )

    def upload_image(self, file_path, file_name, token):
        api_url = self.url + "/api/v1/upload-file"
        headers = {"Authorization": "Bearer {0}".format(token)}

        if not os.path.exists(file_path):
            print("Image [{}] does not exist".format(file_path))
            return None

        with open(file_path, "rb") as img:
            files = [("file", (file_name, img, "image/png"))]

            start_time = datetime.datetime.now()
            response = requests.request(
                "POST", api_url, headers=headers, data={}, files=files
            )
            end_time = datetime.datetime.now()
            delta = end_time - start_time
            if response.status_code == 200:
                data = json.loads(response.text)
                print(
                    "Image [{0}] uploaded with id [{1}] successfully in [{2}]ms".format(
                        file_path, data["id"], int(delta.total_seconds() * 1000)
                    )
                )
                return data["id"]
            else:
                print(f"Image upload failed with response code [{response.status_code}]. Text: {response.text}")
                return None

    @staticmethod
    def generate_image(x_size, y_size, path) -> str:
        image_array = numpy.random.rand(x_size, y_size, 3) * 255
        im = Image.fromarray(image_array.astype("uint8")).convert("RGBA")
        im.save(path)
        return path

    def generate_random_images(self, x_size=250, y_size=250, count=1):
        dir_path = os.path.join(self.data_dir, "random")
        paths = []
        for i in range(count):
            img_path = os.path.join(dir_path, "{0}.png".format(i))
            p = self.generate_image(x_size, y_size, img_path)
            paths.append(img_path)
        return paths

    def generate_dummy_data(self, count):
        self.generate_random_images(250, 250, count)
        self.generate_dummy_metadata(count)

    def generate_dummy_metadata(self, count):
        data = []
        for i in range(count):
            n = random.randint(1, 10)

            rand_words = random.sample(self.words, n)

            data.append({"name": "{0}.png".format(i), "tags": rand_words})

        meta_data = {"images": data}
        meta_data_path = os.path.join(self.data_dir, "random", "metadata.json")

        with open(meta_data_path, "w") as fp:
            json.dump(meta_data, fp)

    def load_random_data(self, count=10, accounts=1):
        self.generate_random_images(100, 100, count)
        print("Random images generated")
        self.generate_dummy_metadata(count)
        print("Random metadata generated")
        metadata_file_path = os.path.join(self.data_dir, "random", "metadata.json")
        data_dir_path = os.path.join(self.data_dir, "random")
        self.load_data(
            metadata_file_path=metadata_file_path, data_dir_path=data_dir_path
        )
        print("Finished loading dummy data")

    def load_random_images(self, count=10, accounts=1, x_size=100, y_size=100):

        login = Login()
        accts = [Account.create() for i in range(accounts)]
        tokens = [login.register_and_login(acct.address, acct.key) for acct in accts]

        dir_path = os.path.join(self.data_dir, "random")
        if not os.path.exists(dir_path):
            os.mkdir(dir_path)

        image_ids = []

        for i in range(count):
            idx = random.randint(0, len(accts) - 1)
            file_path = os.path.join(dir_path, "{0}.png".format(i))
            self.generate_image(x_size, y_size, file_path)
            image_id = self.upload_image(
                file_path, "{0}.png".format(i), tokens[idx]
            )
            os.remove(file_path)
            if image_id is not None:
                image_ids.append(image_id)

        print(f"Finished loading dummy {len(image_ids)} images")
        return image_ids

    def load_random_data2(self, count=10, accounts=1, x_size=100, y_size=100):

        login = Login()
        accts = [Account.create() for i in range(accounts)]
        print("Getting login tokens for [{}] accounts".format(accounts))
        tokens = [login.register_and_login(acct.address, acct.key) for acct in accts]
        for acct in accts:
            print("Public address:{0} key:{1}".format(acct.address, acct.key.hex()))

        dir_path = os.path.join(self.data_dir, "random")
        if not os.path.exists(dir_path):
            os.mkdir(dir_path)

        image_ids = []

        for i in range(count):
            idx = random.randint(0, len(accts) - 1)
            file_path = os.path.join(dir_path, "{0}.png".format(i))
            self.generate_image(x_size, y_size, file_path)
            image_id = self.upload_image(
                file_path, "{0}.png".format(i), tokens[idx],
            )
            os.remove(file_path)

            if image_id is not None:
                idx2 = random.randint(0, len(accts) - 1)
                image_ids.append(image_id)
                self.upload_metadata(
                    tokens[idx2],
                    accts[idx2],
                    image_id,
                    self.get_dummy_metadata(image_id),
                )
        print("Finished loading dummy data")
        return image_ids

    def load_data_with_verification(
            self,
            image_count: int = 10,
            verification_count: int = 10,
            accounts: int = 1,
            x_size: int = 1024,
            y_size: int = 1024,
    ):
        image_ids = self.load_random_data2(image_count, accounts, x_size, y_size)
        for image_id in image_ids:
            DummyDataLoader.add_tags(
                image_id, ["tag2", "tag1", "tag4"], "sample description1"
            )
            DummyDataLoader.add_tags(
                image_id, ["tag1", "tag2", "tag3"], "sample description2"
            )

        for i in range(verification_count):
            DummyDataLoader.mark_as_verified(
                image_ids, ["tag1"], ["tag2"], ["test desc1"], ["test desc2"]
            )

    @staticmethod
    def mark_as_verified(
            image_ids, up_votes, down_votes, desc_up_votes, desc_down_votes
    ):

        for i in image_ids:
            acct = Account.create()
            verify_image_command = VerifyImageCommand(public_address=acct.address, mission_id=None)
            data = {
                "tags": {"up_votes": up_votes, "down_votes": down_votes},
                "descriptions": {
                    "up_votes": desc_up_votes,
                    "down_votes": desc_down_votes,
                },
            }

            verify_image_command.input = {
                "public_address": acct.address,
                "data": data,
                "image_id": i,
            }
            verify_image_command.execute()

    @staticmethod
    def add_tags(image_id, tags, description):
        acct = Account.create()
        add_new_metadata_command1 = AddNewMetadataCommand(public_address=acct.address, mission_id=None)
        add_new_metadata_command1.input = {
            "public_address": acct.address,
            "tags": tags,
            "description": description,
            "image_id": image_id,
        }
        add_new_metadata_command1.execute()

    def load_random_data3(
            self, account=None, token=None, count=10, x_size=100, y_size=100
    ):
        if token is None or account is None:
            print("Token or account is None")
            return

        dir_path = os.path.join(self.data_dir, "random")
        if not os.path.exists(dir_path):
            os.mkdir(dir_path)

        image_ids = []

        for i in range(count):
            file_path = os.path.join(dir_path, "{0}.png".format(i))
            self.generate_image(x_size, y_size, file_path)
            image_id = self.upload_image(file_path, "{0}.png".format(i), token)
            os.remove(file_path)

            if image_id is not None:
                image_ids.append(image_id)
                self.upload_metadata(
                    token, account, image_id, self.get_dummy_metadata(image_id)
                )
        print("Finished loading dummy data")
        return image_ids

    def load_random_images_with_token(
            self, token=None, count=10, x_size=100, y_size=100
    ):
        if token is None:
            print("Token or account is None")
            return

        dir_path = os.path.join(self.data_dir, "random")
        if not os.path.exists(dir_path):
            os.mkdir(dir_path)

        image_ids = []

        for i in range(count):
            file_path = os.path.join(dir_path, "{0}.png".format(i))
            self.generate_image(x_size, y_size, file_path)
            image_id = self.upload_image(file_path, "{0}.png".format(i), token)
            os.remove(file_path)

            if image_id is not None:
                image_ids.append(image_id)
        print(f"Finished loading dummy {len(image_ids)} images")
        return image_ids

    def get_dummy_metadata(self, image_id):
        n = random.randint(1, 10)

        rand_words = random.sample(self.words, n) + ["dog", "cat"]
        return {"image_id": image_id, "tags": rand_words, "description": "text " * 30}


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(
            "Usage: python -m helpers.load_dummy_data <images> <accounts> <x_size> <y_size>"
        )
        exit(-1)

    images = int(sys.argv[1])
    accounts = int(sys.argv[2])

    x_size = 1024
    y_size = 1024

    if len(sys.argv) == 5:
        x_size = int(sys.argv[3])
        y_size = int(sys.argv[4])

    d = DummyDataLoader()
    d.load_random_data3()
    d.load_data_with_verification(
        image_count=images,
        verification_count=8,
        accounts=accounts,
        x_size=x_size,
        y_size=y_size,
    )
