import json
import logging
import os
import shutil
import zipfile
from datetime import datetime
from pathlib import Path
import re
from typing import Optional, List
import mimetypes
from pandas.errors import ParserError
from config import config
import pandas as pd
import time
import base64
from mimetypes import guess_extension, guess_type
from dao.base_dao import DBResultError
from dao.metadata_dao import image_metadata_dao
from commands.base_command import BaseCommand
from models.metadata.annotations.annotation_type import AnnotationType
from models.metadata.metadata_models import EntitySubType, Source
from utils.get_random_string import get_random_string
from flask import request


class DictionaryTooLarge(Exception):
    def __init__(self, key: str):
        self.key = key
        super().__init__(key)

    def __str__(self):
        return f'{self.key}'


class AddNewJsonEntityCommand(BaseCommand):
    def __init__(self, public_address: str, json_entity_type: EntitySubType, raw: dict,
                 parent_data=None, build_avatar=False, source=Source.wedatanation,
                 annotations_required: List[AnnotationType] = (), public=None, doc_id=None):
        super(AddNewJsonEntityCommand, self).__init__(public_address)
        if parent_data is None:
            parent_data = {}
        if public is None:
            public = {}

        self.json_entity_type = json_entity_type
        self.raw = raw
        self.metadata_dao = image_metadata_dao
        self.parent_data = parent_data
        self.build_avatar = build_avatar
        self.source = source
        self.annotations_required = annotations_required
        self.public = public
        self.doc_id = doc_id

    def execute(self):
        if self.doc_id is None:
            parent_doc_id = self.metadata_dao.generate_new_doc_id()
        else:
            parent_doc_id = self.doc_id
        parent_doc_id = self.metadata_dao.add_new_json_entity(parent_doc_id, self.public_address, self.parent_data,
                                                              self.json_entity_type, source=self.source,
                                                              annotations_required=self.annotations_required,
                                                              public=self.public, rewardable=True)
        logging.info(
            f"Data upload: Created parent_doc_id [{parent_doc_id}] for user:[{self.public_address}] entity_sub_type:[{self.json_entity_type}]")

        doc_id = self.metadata_dao.generate_new_doc_id()
        doc_id = self.metadata_dao.add_new_child_entity(doc_id, self.public_address, parent_doc_id, {},
                                                        self.json_entity_type, source=self.source)
        logging.info(
            f"Data upload: Created child_doc_id [{doc_id}] for user:[{self.public_address}] entity_sub_type:[{self.json_entity_type}]")

        doc_ids = [doc_id]
        chunk_count = 0
        key_count = 0
        keys = list(self.raw.keys())
        re_try = False
        while key_count < len(keys):
            key = keys[key_count]
            logging.info("Data upload: processing key [%s] and saving into doc [%s]", key, doc_id)
            try:
                document = self.metadata_dao.get_doc_by_id(doc_id)
                document["raw"][key] = self.raw[key]
                self.metadata_dao.update_doc(doc_id, document)
                self.successful = True
                re_try = False
                key_count += 1
            except DBResultError as e:
                if json.loads(e.message)['error'] == "document_too_large":
                    if re_try is False:
                        doc_id = self.metadata_dao.generate_new_doc_id()
                        chunk_count = chunk_count + 1
                        logging.info("Creating new doc chunk [%s]", doc_id)
                        self.metadata_dao.add_new_child_entity(doc_id, self.public_address, parent_doc_id, {},
                                                               self.json_entity_type,
                                                               chunk_count)
                        logging.info(
                            f"Data upload: Created child_doc_id [{doc_id}] for user:[{self.public_address}] entity_sub_type:[{self.json_entity_type}]")

                        doc_ids.append(doc_id)
                        re_try = True
                    else:
                        # Retry is true but raw object is so large that it cannot be added to document.
                        # So, remove all child docs and parent docs
                        message = f"Failed to save data for user [{self.public_address}]" \
                                  f" because of large content in: [{keys[key_count]}]"
                        logging.warning(message)
                        logging.info("Data upload: Removed parent and child docs")

                        for child_doc_id in doc_ids:
                            image_metadata_dao.delete_doc(child_doc_id)

                        image_metadata_dao.delete_doc(parent_doc_id)

                        raise DictionaryTooLarge(keys[key_count])
                else:
                    logging.exception(str(e), exc_info=e)
                    for child_doc_id in doc_ids:
                        image_metadata_dao.delete_doc(child_doc_id)

                    image_metadata_dao.delete_doc(parent_doc_id)
                    logging.info("Data upload: Removed parent and child docs")
                    self.messages.append("Unable to load data")
                    self.successful = False
                    return

        parent_document = self.metadata_dao.get_doc_by_id(parent_doc_id)
        parent_document["child_docs"] = doc_ids
        self.metadata_dao.update_doc(parent_doc_id, parent_document)
        logging.info("Finished uploading data for user [%s] [%s] with parent_doc_id [%s]",
                     self.public_address, self.json_entity_type, parent_doc_id)
        return parent_doc_id


def nested_set(dic, keys, value):
    for key in keys[:-1]:
        dic = dic.setdefault(key, {})
    dic[keys[-1]] = value


class AddOrReplaceUserMetadataFromFile(BaseCommand):

    def __init__(self, public_address: str, file_path: str):
        super(AddOrReplaceUserMetadataFromFile, self).__init__(public_address)
        self.file_path = file_path

    def execute(self):
        result = image_metadata_dao.query_data({
            "selector": {
                "uploaded_by": self.public_address,
                "json_entity_type": "user_metadata",
                "type": "json",
                "parent": True,
            },
            "limit": 1,
            "fields": [
                "_id", "rev"
            ]
        })['result']

        if len(result) == 1:
            parent_doc_id = result[0]["_id"]
            child_docs = image_metadata_dao.get_child_doc_id(parent_doc_id)
            for c in child_docs:
                image_metadata_dao.delete_doc(c)
            image_metadata_dao.delete_doc(parent_doc_id)
        try:
            with open(self.file_path, "r") as f:
                raw_data = json.load(f)
                doc_id = AddNewJsonEntityCommand(self.public_address, EntitySubType.user_metadata,
                                                 raw_data).execute()
                self.successful = True
                return doc_id
        except Exception as e:
            logging.error(f"Failed to load data for user [{self.public_address}].", exc_info=e)
            self.messages.append("Error while loading data in database.")
            self.successful = False
            return


class AddUserAmazonDataFromZipFile(BaseCommand):

    def __init__(self, public_address: str, file_path: str):
        super(AddUserAmazonDataFromZipFile, self).__init__(public_address)
        self.file_path = file_path

    def execute(self):
        data_directory = os.path.join(config["application"]["upload_folder"], self.public_address, "temp",
                                      EntitySubType.amazon)

        with zipfile.ZipFile(self.file_path, 'r') as zip_ref:
            zip_ref.extractall(data_directory)
        try:
            raw_data = {}
            for subdir, dirs, files in os.walk(data_directory):
                for file in files:
                    if file.endswith(".csv"):
                        f_path = os.path.join(subdir, file)
                        parts = Path(f_path).relative_to(data_directory).parts
                        f_name = file.split('.')[-2]

                        keys = list(parts[:-1]) + [f_name]
                        try:
                            df = pd.read_csv(f_path)
                            json_data = json.loads(df.to_json())
                            nested_set(raw_data, keys, json_data)
                        except ParserError as e:
                            logging.error(f"Skipping file: [{f_path}].", exc_info=e)
                    else:
                        logging.info(f"Skipping file [{os.path.join(subdir, file)}]")

            doc_id = AddNewJsonEntityCommand(self.public_address, EntitySubType.amazon, raw_data).execute()
            shutil.rmtree(data_directory)
            self.successful = True
            return doc_id
        except Exception as e:
            logging.error(f"Failed to load data for user [{self.public_address}].", exc_info=e)
            shutil.rmtree(data_directory)
            self.messages.append("Error while loading data in database.")
            self.successful = False
            return


class AddUserNetflixDataFromZipFile(BaseCommand):

    def __init__(self, public_address: str, file_path: str):
        super(AddUserNetflixDataFromZipFile, self).__init__(public_address)
        self.file_path = file_path

    def execute(self):
        data_directory = os.path.join(config["application"]["upload_folder"], self.public_address, "temp",
                                      EntitySubType.netflix)

        with zipfile.ZipFile(self.file_path, 'r') as zip_ref:
            zip_ref.extractall(data_directory)
        try:
            raw_data = {}
            for subdir, dirs, files in os.walk(data_directory):
                for file in files:
                    if file.endswith(".csv"):
                        f_path = os.path.join(subdir, file)
                        parts = Path(f_path).relative_to(data_directory).parts
                        f_name = file.split('.')[-2]

                        keys = list(parts[:-1]) + [f_name]
                        try:
                            df = pd.read_csv(f_path)
                            json_data = json.loads(df.to_json())
                            nested_set(raw_data, keys, json_data)
                        except ParserError as e:
                            logging.error(f"Skipping file: [{f_path}].", exc_info=e)
                    else:
                        logging.info(f"Skipping file [{os.path.join(subdir, file)}]")
            c = AddNewJsonEntityCommand(self.public_address, EntitySubType.netflix,
                                        raw=raw_data)
            doc_id = c.execute()
            shutil.rmtree(data_directory)
            self.successful = c.successful
            self.messages = c.messages
            return doc_id
        except Exception as e:
            logging.error(f"Failed to load data for user [{self.public_address}].", exc_info=e)
            shutil.rmtree(data_directory)
            raise e


class AddUserZalandoDataFromZipFile(BaseCommand):

    def __init__(self, public_address: str, file_path: str):
        super(AddUserZalandoDataFromZipFile, self).__init__(public_address)
        self.file_path = file_path
        self.json_entity_type = EntitySubType.zalando

    def execute(self):
        data_directory = os.path.join(config["application"]["upload_folder"], self.public_address, "temp",
                                      self.json_entity_type)

        with zipfile.ZipFile(self.file_path, 'r') as zip_ref:
            zip_ref.extractall(data_directory)
        try:
            raw_data = {}
            for subdir, dirs, files in os.walk(data_directory):
                for file in files:
                    if file.endswith(".csv"):
                        f_path = os.path.join(subdir, file)
                        parts = Path(f_path).relative_to(data_directory).parts
                        f_name = file.split('.')[-2]

                        keys = list(parts[:-1]) + [f_name]
                        try:
                            df = pd.read_csv(f_path, sep=";")
                            json_data = json.loads(df.to_json())
                            nested_set(raw_data, keys, json_data)
                        except ParserError as e:
                            logging.error(f"Skipping file: [{f_path}].", exc_info=e)
                    else:
                        logging.info(f"Skipping file [{os.path.join(subdir, file)}]")
            keys = list(raw_data['Zalando'].keys())

            for k in keys:
                new_key = re.sub(r"\d{4}-\d+-\d+_\d+_", "", k)
                raw_data['Zalando'][new_key] = raw_data['Zalando'].pop(k)

            doc_id = AddNewJsonEntityCommand(self.public_address, self.json_entity_type, raw_data).execute()
            shutil.rmtree(data_directory)
            self.successful = True
            return doc_id
        except Exception as e:
            logging.error(f"Failed to load data for user [{self.public_address}].", exc_info=e)
            shutil.rmtree(data_directory)
            self.messages.append("Error while loading data in database.")
            self.successful = False
            return


class AddUserFacebookDataFromZipFile(BaseCommand):

    def __init__(self, public_address: str, file_path: str):
        super(AddUserFacebookDataFromZipFile, self).__init__(public_address)
        self.file_path = file_path

    def execute(self):
        data_directory = os.path.join(config["application"]["upload_folder"], self.public_address, "temp",
                                      EntitySubType.facebook)
        with zipfile.ZipFile(self.file_path, 'r') as zip_ref:
            zip_ref.extractall(data_directory)
        raw_data = {}
        try:

            for subdir, dirs, files in os.walk(data_directory):
                for file in files:
                    if file.endswith(".json"):
                        f_path = os.path.join(subdir, file)
                        parts = Path(f_path).relative_to(data_directory).parts
                        f_name = file.split('.')[-2]

                        keys = list(parts[:-1]) + [f_name]
                        with open(f_path, 'r', encoding='utf-8') as f:
                            json_data = json.load(f)

                        nested_set(raw_data, keys, json_data)
                    else:
                        logging.info(f"Skipping file [{os.path.join(subdir, file)}]")
            doc_id = AddNewJsonEntityCommand(self.public_address, EntitySubType.facebook, raw_data).execute()
            shutil.rmtree(data_directory)
            self.successful = True
            return doc_id

        except Exception as e:
            logging.error(f"Failed to load data for user [{self.public_address}].", exc_info=e)
            shutil.rmtree(data_directory)
            self.messages.append("Error while loading data in database.")
            self.successful = False
            return


class AddUserSpotifyDataFromZipFile(BaseCommand):

    def __init__(self, public_address: str, file_path: str):
        super(AddUserSpotifyDataFromZipFile, self).__init__(public_address)
        self.file_path = file_path
        self.json_entity_type = EntitySubType.spotify

    def execute(self):
        data_directory = os.path.join(config["application"]["upload_folder"], self.public_address, "temp",
                                      self.json_entity_type)
        with zipfile.ZipFile(self.file_path, 'r') as zip_ref:
            zip_ref.extractall(data_directory)
        raw_data = {}
        try:

            for subdir, dirs, files in os.walk(data_directory):
                for file in files:
                    if file.endswith(".json"):
                        f_path = os.path.join(subdir, file)
                        parts = Path(f_path).relative_to(data_directory).parts
                        f_name = file.split('.')[-2]

                        keys = list(parts[:-1]) + [f_name]
                        with open(f_path, 'r', encoding='utf-8') as f:
                            json_data = json.load(f)

                        nested_set(raw_data, keys, json_data)
                    else:
                        logging.info(f"Skipping file [{os.path.join(subdir, file)}]")
            doc_id = AddNewJsonEntityCommand(self.public_address, self.json_entity_type, raw_data).execute()
            shutil.rmtree(data_directory)
            self.successful = True
            return doc_id

        except Exception as e:
            logging.error(f"Failed to load data for user [{self.public_address}].", exc_info=e)
            shutil.rmtree(data_directory)
            self.messages.append("Error while loading data in database.")
            self.successful = False
            return


class AddUserLinkedInDataFromZipFile(BaseCommand):

    def __init__(self, public_address: str, file_path: str, entity_subtype: EntitySubType = EntitySubType.linkedin):
        super(AddUserLinkedInDataFromZipFile, self).__init__(public_address)
        self.file_path = file_path
        self.wedatanation_entity_type = EntitySubType.linkedin
        self.entity_subtype = entity_subtype

    def execute(self):
        data_directory = os.path.join(config["application"]["upload_folder"], self.public_address, "temp",
                                      self.wedatanation_entity_type)

        with zipfile.ZipFile(self.file_path, 'r') as zip_ref:
            zip_ref.extractall(data_directory)
        try:
            raw_data = {}
            for subdir, dirs, files in os.walk(data_directory):
                for file in files:
                    if file.endswith(".csv"):
                        f_path = os.path.join(subdir, file)
                        parts = Path(f_path).relative_to(data_directory).parts
                        f_name = file.split('.')[-2]

                        keys = list(parts[:-1]) + [f_name]
                        try:
                            df = pd.read_csv(f_path)
                            json_data = json.loads(df.to_json())
                            nested_set(raw_data, keys, json_data)
                        except ParserError as e:
                            logging.error(f"Skipping file: [{f_path}].", exc_info=e)
                        except UnicodeDecodeError as e:
                            logging.error(f"Skipping file: [{f_path}].", exc_info=e)
                    else:
                        logging.info(f"Skipping file [{os.path.join(subdir, file)}]")

            doc_id = AddNewJsonEntityCommand(self.public_address, self.entity_subtype,
                                             raw_data).execute()
            shutil.rmtree(data_directory)
            self.successful = True
            return doc_id
        except Exception as e:
            logging.error(f"Failed to load data for user [{self.public_address}].", exc_info=e)
            shutil.rmtree(data_directory)
            self.messages.append("Error while loading data in database.")
            self.successful = False
            return


class AddWedatanationUserDataFromZipFile(BaseCommand):
    def __init__(self, public_address: str, json_entity_type: EntitySubType, file_path: str, storage: str = None):
        super(AddWedatanationUserDataFromZipFile, self).__init__(public_address)
        self.json_entity_type = json_entity_type
        self.file_path = file_path
        self.storage = storage

    def execute(self):

        # check time gating again here. Required because of async arch. The user might submit 2 requests
        # simultaneously and if rabbitmq is busy, new entities are processed later in time. so, when this code runs
        # asynchronously, validate again if user can upload new files.
        c = CheckTimeGatingCommand(public_address=self.public_address, json_entity_type=self.json_entity_type)
        c.execute()
        if c.successful is False:
            self.successful = False
            self.messages = c.messages
            return

        return self.add_entity()

    def add_entity(self):
        c = None
        try:
            if self.json_entity_type == EntitySubType.amazon:
                c = AddUserAmazonDataFromZipFile(self.public_address, self.file_path)
                doc_id = c.execute()
            elif self.json_entity_type == EntitySubType.facebook:
                c = AddUserFacebookDataFromZipFile(self.public_address, self.file_path)
                doc_id = c.execute()
            elif self.json_entity_type == EntitySubType.netflix:
                c = AddUserNetflixDataFromZipFile(self.public_address, self.file_path)
                doc_id = c.execute()
            elif self.json_entity_type == EntitySubType.zalando:
                c = AddUserZalandoDataFromZipFile(self.public_address, self.file_path)
                doc_id = c.execute()
            elif self.json_entity_type == EntitySubType.spotify:
                c = AddUserSpotifyDataFromZipFile(self.public_address, self.file_path)
                doc_id = c.execute()
            elif self.json_entity_type == EntitySubType.user_metadata:
                c = AddOrReplaceUserMetadataFromFile(self.public_address, self.file_path)
                doc_id = c.execute()
            # elif self.json_entity_type == WedataNationEntityType.google:
            #     c = AddUserSpotifyDataFromZipFile(self.public_address, self.file_path)
            #     doc_id = c.execute()
            # elif self.json_entity_type == WedataNationEntityType.twitter:
            #     c = AddUserSpotifyDataFromZipFile(self.public_address, self.file_path)
            #     doc_id = c.execute()
            elif self.json_entity_type == EntitySubType.linkedin:
                c = AddUserLinkedInDataFromZipFile(self.public_address, self.file_path)
                doc_id = c.execute()
            elif self.json_entity_type == EntitySubType.linkedin_part_1:
                c = AddUserLinkedInDataFromZipFile(self.public_address, self.file_path,
                                                   entity_subtype=EntitySubType.linkedin_part_1)
                doc_id = c.execute()
            elif self.json_entity_type == EntitySubType.linkedin_part_2:
                c = AddUserLinkedInDataFromZipFile(self.public_address, self.file_path,
                                                   entity_subtype=EntitySubType.linkedin_part_2)
                doc_id = c.execute()
            elif self.json_entity_type == EntitySubType.survey:
                c = AddSurveyMetadataFromFile(self.public_address, self.file_path, Source.wedatanation, self.storage)
                doc_id = c.execute()
            else:
                self.messages.append("Json entity type not support for zip upload.")
                self.successful = False
                return

            self.successful = True if (c and c.successful) else False
            if not c.successful:
                self.messages = c.messages
                self.successful = False
                return

            return doc_id

        except DictionaryTooLarge as e:
            # Failed to load data. Save zip file
            doc_id = AddNewJsonEntityCommand(self.public_address, self.json_entity_type, raw={},
                                             parent_data={
                                                 "to_be_processed": True
                                             },
                                             annotations_required=[],
                                             public={}).execute()
            c_mime_type = mimetypes.guess_type(self.file_path)[0]
            image_metadata_dao.save_attachment(doc_id=doc_id,
                                               file_name="data",
                                               file_path=self.file_path,
                                               content_type=c_mime_type)
            self.successful = True
            return doc_id
        except Exception as e:
            self.messages.append("Error while loading data in database.")
            self.successful = False
            return


class CheckTimeGatingCommand(BaseCommand):
    def __init__(self, public_address: str, json_entity_type: EntitySubType):
        super(CheckTimeGatingCommand, self).__init__(public_address)
        self.json_entity_type = json_entity_type

    def execute(self):
        time_gated_uploads = [EntitySubType.amazon, EntitySubType.netflix, EntitySubType.linkedin,
                              EntitySubType.linkedin_part_1, EntitySubType.linkedin_part_2, EntitySubType.zalando,
                              EntitySubType.spotify,
                              EntitySubType.facebook, EntitySubType.google]
        if self.json_entity_type in time_gated_uploads:
            selector = {
                "selector": {
                    "uploaded_by": self.public_address,
                    "parent": True,
                    "json_entity_type": self.json_entity_type
                },
                "limit": 1,
                "fields": ["uploaded_at", "_id"],
                "sort": [{"uploaded_at": "desc"}]
            }
            result = image_metadata_dao.query_data(selector=selector)["result"]
            if len(result) > 0:
                minimum_gap_between_uploads = config["wedatanation"].getint("minimum_file_upload_interval", 1)
                time_now = int(datetime.timestamp(datetime.utcnow()))
                upload_time = int(result[0]["uploaded_at"])
                if (time_now - upload_time) < minimum_gap_between_uploads:
                    self.successful = False
                    self.messages.append(f"Upload gap should be at least {minimum_gap_between_uploads}s."
                                         f" Last upload [{result[0]['_id']}] at [{upload_time}]."
                                         f" Try after [{minimum_gap_between_uploads - (time_now - upload_time)}]s.")
                    return

            self.successful = True
            return

        else:
            self.successful = True
            return


class AddSurveyMetadataFromFile(BaseCommand):

    def __init__(self, public_address: str, file_path: str, source: Source, storage: str = None):
        super(AddSurveyMetadataFromFile, self).__init__(public_address)
        self.file_path = file_path
        self.source = source
        self.entity_type = EntitySubType.survey
        self.metadata_dao = image_metadata_dao
        self.storage = storage

    def execute(self):
        try:
            with open(self.file_path, "r", encoding='utf-8') as f:
                parent_data = json.load(f)

                # verify json
                self.successful = True

                required_fields = ['name', 'end_date', 'result_message', 'display_answer_log', 'questions']
                for field in required_fields:
                    if not field in parent_data or parent_data[field] is None:
                        self.messages.append(f"Survey {field} can't be blank")
                        self.successful = False
                for idx, question in enumerate(parent_data['questions']):
                    required_fields = ['question', 'type']
                    for field in required_fields:
                        if not field in question or question[field] is None:
                            self.messages.append(f"Question {idx + 1}: {field} can't be blank")
                            self.successful = False

                    if question['type'] == 'select' or question['type'] == 'select_multiple':
                        if not 'answers_options' in question or not question['answers_options']:
                            self.messages.append(f"Question {idx + 1}: answers_options can't be blank")
                            self.successful = False

                    parent_data['questions'][idx]['id'] = get_random_string(15)

                if not self.successful:
                    return

                doc_id = self.metadata_dao.generate_new_doc_id()
                dir_path = os.path.join(
                    os.path.abspath(os.curdir),
                    config["application"]["upload_folder"],
                    self.public_address,
                    "survey",
                    doc_id
                )
                if not os.path.exists(dir_path):
                    os.makedirs(dir_path)
                try:
                    if 'cover_image' in parent_data.keys():
                        file_type = guess_extension(guess_type(parent_data['cover_image'])[0])
                        file_name = f"cover_image{file_type}"
                        img_data = re.sub(r"^data\:.+base64\,(.+)$", r"\1", parent_data['cover_image'])
                        with open(os.path.join(dir_path, file_name), "wb") as f:
                            f.write(base64.urlsafe_b64decode(img_data))
                        parent_data['cover_image'] = f"{request.host_url}api/v1/metadata/file?entity_type=survey&doc_id={doc_id}&name={file_name}"

                    if 'result_image' in parent_data.keys():
                        file_type = guess_extension(guess_type(parent_data['result_image'])[0])
                        file_name = f"result_image{file_type}"
                        img_data = re.sub(r"^data\:.+base64\,(.+)$", r"\1", parent_data['result_image'])
                        with open(os.path.join(dir_path, file_name), "wb") as f:
                            f.write(base64.urlsafe_b64decode(img_data))
                        parent_data['result_image'] = f"{request.host_url}api/v1/metadata/file?entity_type=survey&doc_id={doc_id}&name={file_name}"
                except Exception as e:
                    print(e)
                    pass

                for idx, question in enumerate(parent_data['questions']):
                    try:
                        if 'image' in question.keys():
                            file_type = guess_extension(guess_type(question['image'])[0])
                            file_name = f"question_image_{question['id']}{file_type}"
                            img_data = re.sub(r"^data\:.+base64\,(.+)$", r"\1", question['image'])
                            with open(os.path.join(dir_path, file_name), "wb") as f:
                                f.write(base64.urlsafe_b64decode(img_data))
                            parent_data['questions'][idx]['image'] = f"{request.host_url}api/v1/metadata/file?entity_type=survey&doc_id={doc_id}&name={file_name}"
                    
                        if 'result_image' in question.keys():
                            file_type = guess_extension(guess_type(question['result_image'])[0])
                            file_name = f"question_result_image_{question['id']}{file_type}"
                            img_data = re.sub(r"^data\:.+base64\,(.+)$", r"\1", question['result_image'])
                            with open(os.path.join(dir_path, file_name), "wb") as f:
                                f.write(base64.urlsafe_b64decode(img_data))
                            parent_data['questions'][idx]['result_image'] = f"{request.host_url}api/v1/metadata/file?entity_type=survey&doc_id={doc_id}&name={file_name}"
                    
                    except Exception as e:
                        print(e)
                        pass

                doc_id = AddNewJsonEntityCommand(self.public_address, self.entity_type, raw={},
                                                 parent_data=parent_data,
                                                 annotations_required=[AnnotationType.survey_response],
                                                 public=parent_data, doc_id=doc_id).execute()
                return doc_id
        except Exception as e:
            logging.error(f"Failed to load data for user [{self.public_address}].", exc_info=e)
            self.messages.append("Error while loading data in database.")
            self.successful = False
            return
