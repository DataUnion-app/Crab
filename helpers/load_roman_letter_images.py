import logging
import argparse
import sys
import os
from commands.metadata.add_new_image_command import AddNewImageCommand
from commands.metadata.add_new_metadata_command import AddNewMetadataCommand
from config import config

logging.basicConfig(stream=sys.stdout, level=logging.INFO)

parser = argparse.ArgumentParser()
parser.add_argument("-a", "--address",
                    help="A wallet address", required=True)

parser.add_argument("-p", "--path",
                    help="Path where all images are stored", required=True)


def add_tags(address: str, image_id: str, roman_letter: str):
    mc = AddNewMetadataCommand(public_address=address, mission_id=None)
    mc.input = {
        "public_address": address,
        "tags": [roman_letter, "roman-letter-bounty"],
        "image_id": image_id,
    }
    mc.execute()

    if not mc.successful:
        logging.error("Unable to add metadata for [%s]. Messages: [%s]", image_id, mc.messages)


if __name__ == "__main__":
    args = parser.parse_args()
    dir_path = args.path

    public_address = args.address

    if not os.path.exists(dir_path):
        logging.error("Path [%s] does not exists", dir_path)
        exit(-1)

    upload_dir = os.path.join("data", public_address)
    if not os.path.exists(upload_dir):
        os.makedirs(upload_dir)

    for root, dirs, files in os.walk(dir_path, topdown=False):
        for name in dirs:
            dir_name = os.path.join(root, name)
            image_files = os.listdir(dir_name)

            roman_letter_tag = name

            logging.info("Loading [%s] images in [%s]", len(image_files), dir_name)
            for image_file in image_files:
                if not image_file.endswith(".png"):
                    logging.info("Skipping file [%s]", image_file)
                    continue
                image_path = os.path.join(dir_name, image_file)
                a = AddNewImageCommand(public_address, image_path, bounty_name=["roman-letter-bounty"],
                                       use_hashing=False,
                                       validate_dimensions=False)

                doc_id = a.execute()

                if not a.successful:
                    logging.error("Unable to load image [%s]. Messages: %s. doc-id: %s", image_path, a.messages, doc_id)
                    continue
                add_tags(public_address, doc_id, name)
