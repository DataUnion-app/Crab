import glob
import json
import os.path
import sys
import logging
from os import path
from typing import List

import requests

import getpass

from commands.metadata.add_annotation_command import AddTrueTagAnnotationCommand

logging.basicConfig()
logging.getLogger().setLevel(logging.INFO)

from helpers.login import Login
from models.metadata.annotations.annotation_type import AnnotationType


def get_token(public_address: str, private_key: str) -> str:
    login = Login()
    exists, nonce = login.user_exists(public_address)

    if exists:
        token = login.login(public_address, private_key).get('access_token')
    else:
        token = login.register_and_login(public_address, private_key)
    if token is None:
        logging.error("Access token is None")
        sys.exit(-1)
    return token


def upload_image(token: str, image_path: path, server_endpoint: str = "http://localhost:8080",
                 annotations: str = """[]""") -> str:
    headers = {"Authorization": "Bearer {0}".format(token)}

    api_url = server_endpoint + "/api/v1/upload-file"

    payload = {
        "annotations": annotations
    }

    with open(image_path, "rb") as img:
        files = [("file", (os.path.split(image_path)[-1], img, "image/jpeg"))]

        response = requests.request(
            "POST", api_url, headers=headers, data=payload, files=files
        )
        if response.status_code != 200:
            logging.error(f"Failed to upload image [{image_path}]. Error: [{response.text}]")
            return
        data = json.loads(response.text)
        image_id = data["id"]
        assert image_id is not None

        logging.info(f"Uploaded image with [{image_id}]")
        return image_id


if __name__ == "__main__":
    acct_address = input("Address: ".format(getpass.getuser()))
    acct_key = getpass.getpass(prompt="Private key:")

    access_token = get_token(acct_address, acct_key)
    logging.info("Access token generated")

    image_dir_path = os.path.join("staging", "nCight", "Pilot Images")
    if not os.path.isdir(image_dir_path):
        logging.error(f"Path does not exist: [{image_dir_path}]")
        sys.exit(-1)

    knee_image_path = os.path.join(image_dir_path, "Knee")
    knee_images = glob.glob(knee_image_path + '/**/*.jpeg', recursive=True)

    for image_path in knee_images:
        annotations = [{
            "type": AnnotationType.TrueTag,
            "tags": ["knee"]
        }]

        image_id = upload_image(token=access_token, image_path=image_path, annotations=json.dumps([]))
        if image_id:
            c = AddTrueTagAnnotationCommand(public_address=acct_address, image_id=image_id, annotations=annotations)
            c.execute()
            if c.successful is False:
                logging.error(f"Failed to add TrueTag annotation for image [{image_id}]")

    shoulder_image_path = os.path.join(image_dir_path, "Shoulder")
    shoulder_images = glob.glob(shoulder_image_path + '/**/*.jpeg', recursive=True)

    for image_path in shoulder_images:
        annotations = [{
            "type": AnnotationType.TrueTag,
            "tags": ["shoulder"]
        }]

        image_id = upload_image(token=access_token, image_path=image_path, annotations=json.dumps([]))
        if image_id:
            c = AddTrueTagAnnotationCommand(public_address=acct_address, image_id=image_id, annotations=annotations)
            c.execute()
            if c.successful is False:
                logging.error(f"Failed to add TrueTag annotation for image [{image_id}]")
