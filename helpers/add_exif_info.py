import argparse
from commands.metadata.add_exif_data_command import AddExifDataCommand
import sys
import logging
from dao.metadata_dao import image_metadata_dao

logging.basicConfig(stream=sys.stdout, level=logging.INFO)

parser = argparse.ArgumentParser()
parser.add_argument("-all", "--all-docs", type=bool, default=False, action=argparse.BooleanOptionalAction,
                    help="Add exif info for all documents.")
parser.add_argument('-i', '--image-ids', nargs='+', help='Provide list of image ids', required=False)

args = parser.parse_args()

if __name__ == "__main__":

    doc_ids = []
    if args.all_docs:
        doc_ids = [doc_info['id'] for doc_info in image_metadata_dao.get_all_doc_id()]
    else:
        logging.info("Adding exif info for: %s", args.image_ids)
        for image_id in args.image_ids:
            if image_metadata_dao.exists(image_id):
                doc_ids.append(image_id)
            else:
                logging.warning("[%s] image id does not exist", image_id)

    for index, doc_id in enumerate(doc_ids):
        image_id = doc_id
        command = AddExifDataCommand(image_id=image_id)
        command.execute()
        if command.successful:
            logging.info("[%s/%s]: Added exif info for [%s] successfully", index + 1, len(doc_ids), image_id)
        else:
            logging.error("[%s/%s]: Failed to load exif info for [%s]", index + 1, len(doc_ids), image_id)
