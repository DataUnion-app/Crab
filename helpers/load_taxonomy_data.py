import os
import json
import sys
from commands.taxonomy.add_taxonomy_data import AddTaxonomyData
from config import config
from models.taxonomy.TaxonomyImageStatus import TaxonomyImageStatus
from models.taxonomy.TaxonomyTypes import TaxonomyTypes
from utils.get_project_dir import get_project_root
from utils.get_random_string import get_random_string
import logging
from shutil import copyfile, copytree


def load_taxonomy_data(data_dir: str):
    if not os.path.isdir(data_dir):
        logging.error("[%s] is not a directory. Exiting", data_dir)
        exit(-1)

    crop_image_dir = os.path.join(data_dir, "crops")
    if not os.path.isdir(crop_image_dir):
        logging.error("[%s] is not a directory. Exiting", crop_image_dir)
        exit(-1)

    label_image_dir = os.path.join(data_dir, "german_icons")
    if not os.path.isdir(label_image_dir):
        logging.error("[%s] is not a directory. Exiting", label_image_dir)
        exit(-1)
    else:
        dest = config["taxonomy"]["labels_folder"]
        copytree(label_image_dir, dest, dirs_exist_ok=True)

    crop_data_path = os.path.join(data_dir, "crop_labels.json")
    if not os.path.isfile(crop_data_path):
        logging.error("[%s] is not a file. Exiting", crop_data_path)
        exit(-1)

    # data_dir = os.path.join(get_project_root(), 'helpers', 'data', 'taxonomy')
    target_dir = os.path.join(get_project_root(), config["taxonomy"]["image_folder"])

    with open(crop_data_path, "r") as crop_data_file:
        crop_data_content = json.load(crop_data_file)

    for crop_data in crop_data_content:
        for key, crop in crop_data.items():
            # img_path = os.path.join(image_data_dir, crop["filename"])

            status = TaxonomyImageStatus.VERIFIABLE.name
            src_image_path = os.path.join(crop_image_dir, crop["filename"])
            doc_id = get_random_string()
            image_path = os.path.join(
                target_dir, doc_id + os.path.splitext(crop["filename"])[1]
            )

            if not os.path.isfile(src_image_path):
                status = TaxonomyImageStatus.MISSING_FILE_WHILE_LOAD.name
                logging.warning(
                    f"Crop image not found at path [{src_image_path}] during taxonomy data load."
                )
            else:
                copyfile(src_image_path, image_path)

            if crop["status"] == "skipped":
                status = TaxonomyImageStatus.SKIPPED

            add_taxonomy = AddTaxonomyData()
            add_taxonomy.input = {
                "image_id": doc_id,
                "image_path": image_path,
                "type": TaxonomyTypes.CROP.name,
                "label": crop["label"],
                "filename": crop["filename"],
                "x_top": int(crop["x_top"]),
                "y_top": int(crop["y_top"]),
                "x_bot": int(crop["x_bot"]),
                "y_bot": int(crop["y_bot"]),
                "status": status,
                "class": "test",
                "description": "test desc",
            }
            add_taxonomy.execute()

            if not add_taxonomy.successful:
                logging.error(f"Unable to add taxonomy data {add_taxonomy.messages}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python -m helpers.load_taxonomy_data <data_directory_path>")
        exit(-1)

    data_dir_path = sys.argv[1]
    load_taxonomy_data(data_dir_path)
