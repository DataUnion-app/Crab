import sys
import os
import csv
from dao.device_dao import device_dao
from models.metadata.metadata_models import Source

def add_devices(file_path: str) -> None:
    if not os.path.exists(file_path):
        print("Error: File [{0}] does not exist".format(file_path))
        exit(-1)

    with open(file_path, "r") as f:
        reader = csv.DictReader(f)
        for row in reader:
            device_dao.create_device(document=row, source=Source.brainstem)

    print("Devices added successfully")

if __name__ == "__main__":

    if len(sys.argv) < 2:
        print("Usage: python -m helpers.add_devices <file_name>")
        exit(-1)

    file = os.path.join("data", sys.argv[1])
    add_devices(file)
