import logging

import jwt
import ssl
import time

from pymongo import MongoClient

from celery import Celery

from commands.dataunions.ncights.generate_notifications import GenerateNcightNotifications
from commands.dataunions.wedatanation.add_json_entity_command import AddWedatanationUserDataFromZipFile
from commands.dataunions.wedatanation.fetch_avatar import FetchUserAvatar
from config import config
from datetime import datetime
from urllib.parse import quote

from commands.metadata.add_exif_data_command import AddExifDataCommand
from commands.metadata.get_image_for_verification import GetImageForVerification


# Celery configuration
from models.metadata.metadata_models import EntitySubType, Source

RABBITMQ_USERNAME = quote(config["rabbitmq"]["username"], safe="")
RABBITMQ_PASSWORD = quote(config["rabbitmq"]["password"], safe="")
RABBITMQ_HOST = config["rabbitmq"]["host"]
RABBITMQ_PORT = config["rabbitmq"]["port"]
CELERY_BROKER_URL = f"pyamqp://{RABBITMQ_USERNAME}:{RABBITMQ_PASSWORD}@{RABBITMQ_HOST}:{RABBITMQ_PORT}/"
CELERY_RESULT_BACKEND = "rpc://"
MAX_MESSAGES_QUEUE = 15

celery_beat_schedule = {
    "time_scheduler": {
        "task": "task_handler.worker.generate_notifications",
        # Run every second
        "schedule": config["application"].getint("ncight_notification_task_interval"),
    }
}

# Initialize Celery
celery = Celery('task_handler',
                broker=CELERY_BROKER_URL,
                backend=CELERY_RESULT_BACKEND)
celery_config = {"beat_schedule": celery_beat_schedule}
if config["rabbitmq"].getboolean("use_tls", fallback=True):
    celery_config["broker_use_ssl"] = {
        'ca_certs': f'{config["rabbitmq"]["certs_directory"]}/cacert.pem',
        'keyfile': f'{config["rabbitmq"]["certs_directory"]}/key.pem',
        'certfile': f'{config["rabbitmq"]["certs_directory"]}/cert.pem',
        'cert_reqs': ssl.CERT_REQUIRED
    }
celery.conf.update(**celery_config)


@celery.task(bind=True)
def add_exif_and_verify_image(self, kwargs):
    image_id = kwargs.get('image_id')
    add_exit_cmd = AddExifDataCommand(image_id)
    add_exit_cmd.execute()

    if not add_exit_cmd.successful:
        raise ValueError(f'Loading exif data error - id: {image_id}')

    img_verify_command = GetImageForVerification(image_id)
    verified_result = img_verify_command.execute()

    if not img_verify_command.successful:
        raise ValueError(f'Image verification failed - id: {image_id}')


@celery.task(bind=True)
def sensor_processor(self, kwargs):
    ins = celery.control.inspect()
    try:
        while True:
            queue_over_max_length_for_worker_1 = False
            all_stats = ins.stats()
            if all_stats is None:
                msg = "No Celery Workers have been detected."
                print(msg)
                raise RuntimeError(msg)
            for k in all_stats.keys():
                if k.startswith('celery@handler') \
                        and all_stats[k]['pool'].get('running-threads', 0) >= MAX_MESSAGES_QUEUE:
                    queue_over_max_length_for_worker_1 = True
            if queue_over_max_length_for_worker_1:
                print(f"The DB queue is above {MAX_MESSAGES_QUEUE} pausing for 5 seconds.")
                time.sleep(5)
            else:
                break

        access_token = kwargs.get('access_token')

        try:
            result = jwt.decode(access_token, options={"verify_signature": False})
            print('The jwt access token has been successfully decoded!')
            print(result)
        except Exception as error:
            print(error)
            return

        with MongoClient(host=f"{config['MONGODB']['HOST']}:{config['MONGODB']['PORT']}",
                         username=f"{config['MONGODB']['USERNAME']}",
                         password=f"{config['MONGODB']['PASSWORD']}") as client:
            sensor_collection = client[config['MONGODB']['DATABASE']][config['MONGODB']['COLLECTION']]
            sensor_collection.insert_one({
                "sensor": kwargs.get('sensor_data', ''),
                "timestamp": datetime.now().timestamp(),
                "wallet_address": kwargs.get('wallet_address', '')
            })
    except Exception as error:
        msg = f"Error in processing the message: {error}"
        print(msg)
        raise RuntimeError(msg)


@celery.task(bind=True)
def build_user_avatar(self, kwargs):
    from commands.dataunions.wedatanation.build_user_avatar_command import BuildUserAvatarCommand

    public_address = kwargs.get('public_address')

    task_id = celery.current_task.request.id

    print(f"Celery task id for avatar creation for user [{public_address}] is [{task_id}]")
    build_avatar_cmd = BuildUserAvatarCommand(public_address, task_id=task_id)
    result = build_avatar_cmd.execute()

    f = FetchUserAvatar(public_address, result["avatar"], True)
    result = f.execute()

    if not build_avatar_cmd.successful:
        raise ValueError(f'Error executing BuildUserAvatarCommand for [{public_address}]')

    if not f.successful:
        raise ValueError(f'Error executing FetchUserAvatar for [{public_address}]')
    return result


@celery.task(bind=True)
def generate_notifications(self):
    c = GenerateNcightNotifications(check_new_users=True)
    c.execute()


@celery.task(bind=True)
def upload_user_data(self, kwargs):
    public_address = kwargs.get('public_address')

    json_entity_type = EntitySubType(kwargs.get('json_entity_type'))
    zip_file_path = kwargs.get('zip_file_path')

    logging.info("AddWedatanationUserDataFromZipFile: Starting to execute with input [%s] [%s] [%s]", public_address,
                 json_entity_type, zip_file_path)
    add_user_data_command = AddWedatanationUserDataFromZipFile(public_address, json_entity_type, zip_file_path)
    result = add_user_data_command.execute()

    logging.info("AddWedatanationUserDataFromZipFile: Execute status: [%s]", add_user_data_command.successful)
    logging.info("AddWedatanationUserDataFromZipFile: Result: [%s]", result)
    logging.info("AddWedatanationUserDataFromZipFile: Messsages: [%s]", add_user_data_command.messages)
