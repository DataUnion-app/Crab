import json
import logging
import os
from datetime import datetime, timezone

import pandas as pd

from commands.base_command import BaseCommand
from config import config
from dao.metadata_dao import image_metadata_dao
from dao.base_dao import DBResultError
from dao.rewards_dao import rewards_dao
from dao.users_dao import user_dao
from models.metadata.metadata_models import Source, EntitySubType
from models.rewards.rewards_model import TaskType
from models.metadata.annotations.annotation_type import AnnotationType
from commands.metadata.upload_ipfs_command import UploadIpfsCommand
from commands.dataunions.brainstem.record_contract import CONTRACT_VERSION
from commands.dataunions.brainstem.record_projection import project_record_on_user


class CreateBrainStemEntityCommand(BaseCommand):
    def __init__(self, public_address: str, file_path: str, file_type: EntitySubType, media_type: str,
                 original_file_name: str, storage: str = None, document_id: str = None,
                 record_data: dict = None, record_summary=None, content_hash: str = None):
        super().__init__(public_address)
        self.file_path = file_path
        self.source = Source.brainstem
        self.media_type = media_type
        self.file_type = file_type
        self.original_file_name = original_file_name
        self.storage = storage
        self.document_id = document_id
        self.record_data = record_data
        self.record_summary = record_summary
        self.content_hash = content_hash

    def execute(self):
        self.successful = False
        try:
            # Generate document IDs
            doc_id = self.document_id or image_metadata_dao.generate_new_doc_id()
            child_doc_id = (
                None
                if self.file_type == EntitySubType.record
                else image_metadata_dao.generate_new_doc_id()
            )

            # Base document
            document = {
                "created_at": datetime.utcnow().isoformat(),
                "updated_at": datetime.utcnow().isoformat(),
                "created_by": self.public_address,
                "file_path": "",
                "file_type": self.file_type,
                "source": self.source,
                "type": self.media_type,
                "available_for_annotation": True,
                "available_for_verification": False,
                "available_for_download": False,
                "original_file_name": self.original_file_name,
                "annotations_required": [AnnotationType.peaq_did],
                "child_docs": [child_doc_id] if child_doc_id else [],
                "user_submissions": {AnnotationType.peaq_did: []}
            }

            destination_path = self.file_path

            already_exists, existing_document = image_metadata_dao.get_if_exists(doc_id)

            # Handle IPFS / Filecoin storage
            if already_exists and self.file_type == EntitySubType.record:
                document = existing_document
            elif self.storage == "ipfs":
                c = UploadIpfsCommand(self.file_path)
                result = c.execute()
                if c.successful:
                    document["file_path"] = result["url"]
                    document["storage"] = self.storage
            elif self.storage == "filecoin":
                self.messages.append("Filecoin storage is retired")
                return

            # Local upload if no storage path
            if not already_exists and not document["file_path"]:
                upload_dir = os.path.join(config["application"]["upload_folder"], self.public_address)
                os.makedirs(upload_dir, exist_ok=True)
                filename = os.path.basename(self.file_path)
                destination_path = os.path.join(upload_dir, f"{doc_id}-{filename}")
                os.rename(self.file_path, destination_path)
                document["file_path"] = destination_path
                document["storage"] = ""

            # Process file types
            if self.file_type == EntitySubType.over_chunk:
                try:
                    df = pd.read_csv(destination_path, delim_whitespace=True)
                    document["start_date_time"] = ((df["Date"] + " " + df["StartTime"]).astype(str)).iloc[0]
                    document["stop_date_time"] = ((df["Date"] + " " + df["StopTime"]).astype(str)).iloc[-1]
                except Exception as e:
                    logging.exception(f"Error processing over_chunk CSV: {destination_path}", exc_info=e)
                image_metadata_dao.save(doc_id, document)

            elif self.file_type == EntitySubType.hbr_rr:
                try:
                    with open(destination_path, 'r') as f:
                        first_reading = f.readline().strip().split()
                        last_reading = []
                        for line in f:
                            if line.strip() == '':
                                break
                            last_reading = line.strip().split()
                        document["raw"] = open(destination_path, 'r').read()
                        document["first_reading"] = first_reading
                        document["last_reading"] = last_reading
                    image_metadata_dao.save(doc_id, document)
                except Exception as e:
                    logging.exception(f"Unable to process hbr_rr file: {destination_path}", exc_info=e)

            elif self.file_type == EntitySubType.user_metadata:
                try:
                    with open(destination_path, 'r') as f:
                        document["user_metadata"] = json.load(f)
                    image_metadata_dao.save(doc_id, document)
                except Exception as e:
                    logging.exception(f"Unable to process user_metadata JSON: {destination_path}", exc_info=e)

            elif self.file_type == EntitySubType.heartbeat:
                document["available_for_download"] = True
                image_metadata_dao.save(doc_id, document)

            elif self.file_type == EntitySubType.summary:
                image_metadata_dao.save(doc_id, document)

            elif self.file_type == EntitySubType.record:
                data = self.record_data
                summary = self.record_summary
                if data is None or summary is None:
                    raise ValueError("Validated Brainstem record contract is required")

                record_updates = {
                    "record_type": summary.record_type,
                    "sensor_name": data.get('datasource', {}).get('sensor', {}).get('name'),
                    "sensor_id": data.get('datasource', {}).get('sensor', {}).get('id'),
                    "t0": summary.t0,
                    "duration": summary.duration,
                    "rows": summary.rows,
                    "valid_rr_intervals": summary.valid_rr_intervals,
                    "record_contract_version": CONTRACT_VERSION,
                    "recognized_payloads": list(summary.recognized_payloads),
                    "reward_eligible": summary.reward_eligible,
                    "reward_reason": summary.reward_reason,
                    "content_hash": self.content_hash,
                }
                if "accepted_at_utc" not in document:
                    record_updates["accepted_at_utc"] = (
                        datetime.now(timezone.utc)
                        .isoformat(timespec="seconds")
                        .replace("+00:00", "Z")
                    )
                if summary.captured_at_utc is not None:
                    record_updates["captured_at_utc"] = summary.captured_at_utc
                if 'metadata' in data:
                    record_updates["metadata"] = data['metadata']
                document.update(record_updates)
                if already_exists:
                    document = image_metadata_dao.mutate_doc(
                        doc_id,
                        lambda current: {**current, **record_updates},
                    )
                else:
                    try:
                        image_metadata_dao.save(doc_id, document)
                    except DBResultError:
                        exists_after_conflict, _ = image_metadata_dao.get_if_exists(doc_id)
                        if not exists_after_conflict:
                            raise

                # Update user recording data
                user_result = user_dao.get_by_public_address(self.public_address).get("result", [])
                if not user_result:
                    raise ValueError(f"User not found: {self.public_address}")
                user = user_result[0]

                projected_user, changed = project_record_on_user(
                    user, doc_id, summary, document.get("metadata")
                )
                if changed:
                    user_dao.mutate_doc(
                        user["_id"],
                        lambda current: project_record_on_user(
                            current, doc_id, summary, document.get("metadata")
                        )[0],
                    )

                if summary.reward_eligible:
                    rewards_dao.create_brainstem_eligibility(
                        self.public_address,
                        doc_id,
                        summary.reward_amount,
                        TaskType(summary.reward_task_type),
                        summary.reward_kind,
                    )

            if child_doc_id:
                image_metadata_dao.add_new_child_entity(
                    child_doc_id, self.public_address, doc_id, {}, self.file_type,
                    source=self.source
                )

            self.successful = True
            return doc_id

        except Exception as e:
            logging.exception("Failed to create brainstem entity", exc_info=e)
            self.messages.append(str(e))
            self.successful = False
            return None
