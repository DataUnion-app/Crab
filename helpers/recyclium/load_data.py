import random
from datetime import datetime, timedelta
from typing import List, Optional
from config import config
from dao.users_dao import user_dao
from helpers.load_dummy_data import DummyDataLoader
from models.bounty import BountyType
from models.entity_list_models import EntityListType
from models.metadata.metadata_models import EntityType, Source
from commands.bounty.bounty_commands import CreateBountyCommand
from commands.entity_lists.create_entity_list_command import CreateEntityListCommand
from commands.metadata.upload_media_command import UploadMediaCommand
from models.missions import MissionType
from commands.missions.add_missions import CreateMissionsFromBountyCommand
from commands.metadata.add_annotation_command import AddAnnotationCommand
from utils.get_random_string import get_random_string

def create_users() -> None:
    users = [
        {
            "public_address": config["recyclium_dummy_users"]["admin_address"],
            "profile": {
                "email": "admin@example.com"
            },
            "claims": ["admin"]
        },
        {
            "public_address": config["recyclium_dummy_users"]["creator_address"],
            "claims": ["creator"],
            "profile": {
                "email": "creator@example.com",
                "company_title": "Data Union",
                "address": "3020 Yorba Linda Blvd",
                "country": "USA"
            }
        },
        {
            "public_address": config["recyclium_dummy_users"]["storer_address"],
            "claims": ["storer"],
            "profile": {
                "name": "Storer",
                "email": "storer@example.com",
                "address": "3020 Yorba Linda Blvd",
                "city": "Fullerton",
                "country": "USA",
                "worktime": "8a - 8p",
                "storageSpace": 1000,
                "geocode": {
                "lat": 33.8,
                "lng": -117.8
                },
                "postalCode": "92831"
            }
        },
        {
            "public_address": config["recyclium_dummy_users"]["collector_address"],
            "profile": {
                "email": "collector@example.com"
            },
            "claims": ["user"]
        }
    ]

    for user in users:
        try:
            doc_id = user_dao.create_user(user["public_address"], user["claims"], user["profile"])
            print("User craeted successfully: {}".format(doc_id))
        except Exception as e:
            print("User not added. {}".format(e))



def create_bounty(public_address: str, bounty_type=BountyType.IMAGE_UPLOAD, image_uploads: Optional[int] = 0,
                        number_of_verifications: Optional[int] = 0,
                        number_of_annotations: Optional[int] = 0, entity_list_ids: List[str] = None) -> dict:

    images = generate_random_images(2)
    try:
        c = CreateBountyCommand(public_address, 'cname', 'cd', bounty_type, 'bname', 'bd', datetime.today(),
                                datetime.today() + timedelta(days=1), images[0], images[1], ['x', 'y'' z'], [], '',
                                [], 'test-dataset', image_uploads, number_of_verifications, number_of_annotations,
                                entity_list_ids)
        result = c.execute()
    except Exception as e:
        pass
    if c.successful:
        return result
    else:
        print(f"Messages: {c.messages}")


def create_missions(public_address: str, mission_type: MissionType = MissionType.UPLOAD,
                            bounty_id: Optional[str] = None) -> str:
    try:
        c = CreateMissionsFromBountyCommand(public_address=public_address, mission_type=mission_type,
                                            bounty_id=bounty_id, target=1)
        result = c.execute()

        if c.successful is True:
            return result
        else:
            print(f"Messages: {c.messages}")
    except Exception as e:
        print(e)

def generate_random_images(count=1):
    dummy_data_loader = DummyDataLoader()
    image_paths = dummy_data_loader.generate_random_images(100, 100, count)
    return image_paths

def create_entity_list(public_address: str, entity_ids, entity_type: EntityType = EntityType.image,
                                entity_list_type: EntityListType = EntityListType.PRIVATE) -> str:

    c = CreateEntityListCommand(public_address, entity_type, entity_list_type, entity_ids, "test", "Test", None, Source.recyclium)
    new_list_id = c.execute()
    return new_list_id

def add_random_image(public_address: str, bounty: str = None, mission_id: str = None) -> str:
    dummy_data_loader = DummyDataLoader()
    image_path = dummy_data_loader.generate_random_images(600, 600, 1)[0]

    try:
        qr_code = get_random_string(15)
        add_new_image_c = UploadMediaCommand(file=image_path,
                                            uploaded_by=public_address,
                                            bounty=bounty,
                                            mission_id=mission_id,
                                            source=Source.recyclium,
                                            qr_code=qr_code)
        result = add_new_image_c.execute()
    except Exception as e:
        pass

    latitude = random.uniform(-180, 180)
    longitude = random.uniform(-180, 180)

    if latitude and longitude:
        new_annotations = [{
            "type": "location",
            "latitude": float(latitude),
            "longitude": float(longitude),
            "locality": "",
            "city": ""
        }]

        add_annotation_command = AddAnnotationCommand(
            public_address=public_address,
            entity_id=result,
            annotations=new_annotations,
            mission_id=None
        )
        add_annotation_command.execute()

        if not add_annotation_command.successful:
            print(add_annotation_command.messages)

    if add_new_image_c.successful is True:
        return result
    else:
        print(f"Messages: {add_new_image_c.messages}")

    return result

def create_bounty_items(public_address: str, bounty: str = None, mission_id: str = None, count: int = 10):
    doc_ids = []

    for i in range(count):
        doc_id = add_random_image(public_address, bounty, mission_id)
        doc_ids.append(doc_id)
    
    return doc_ids

if __name__ == "__main__":
    create_users()
    print("Users created")

    bounty = create_bounty(config["recyclium_dummy_users"]["creator_address"])
    print("Bounty created. {}".format(bounty))

    missions = create_missions(config["recyclium_dummy_users"]["creator_address"], MissionType.UPLOAD, bounty["id"])
    print("Missions created. {}".format(missions))

    bounty_item_ids = create_bounty_items(config["recyclium_dummy_users"]["collector_address"], 'bname', missions[0])
    print("Bounty Items created. {}".format(bounty_item_ids))

    entity_list_id = create_entity_list(config["recyclium_dummy_users"]["collector_address"], bounty_item_ids)
    print("Entity list created. {}".format(entity_list_id))
