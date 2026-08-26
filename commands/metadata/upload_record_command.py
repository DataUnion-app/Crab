import os
import json
import hashlib
from commands.metadata.create_new_entity.create_brainstem_entity import CreateBrainStemEntityCommand, EntitySubType
from commands.dataunions.brainstem.consent import has_legacy_mobile_consent
from commands.dataunions.brainstem.record_contract import (
    RecordValidationError,
    parse_record,
)
from config import config
from models.metadata.metadata_models import Source
from werkzeug.utils import secure_filename
from commands.base_command import BaseCommand
from dao.metadata_dao import image_metadata_dao
from dao.users_dao import user_dao

class UploadRecordCommand(BaseCommand):
    def __init__(self,
                 file,
                 uploaded_by: str,):
        super().__init__()
        self.file = file
        self.uploaded_by = uploaded_by
        self.image_metadata_dao = image_metadata_dao
        self.source = Source.brainstem
        self.file_type = "record"
        self.error_status = 400
        self.record_data = None
        self.record_summary = None

    def execute(self):
        users = user_dao.get_by_public_address(self.uploaded_by).get("result", [])
        if len(users) != 1 or not has_legacy_mobile_consent(users[0]):
            self.successful = False
            self.error_status = 403
            self.messages.append("Brainstem data consent is required")
            return None

        dir_path = os.path.join(
            os.path.abspath(os.curdir),
            config["application"]["upload_folder"],
            self.uploaded_by, "temp"
        )
        if not os.path.exists(dir_path):
            os.makedirs(dir_path)
        filename = secure_filename(self.file.filename)
        file_path = os.path.join(dir_path, filename)
        relative_filepath = os.path.join(
            os.path.abspath(os.curdir),
            config["application"]["upload_folder"],
            self.uploaded_by, "temp",
            filename
        )
        self.file.save(file_path)

        if not self.validate_json(file_path):
            self.successful = False
            os.unlink(file_path)
            return

        result = None
        try:
            brainstem_file_type = EntitySubType[self.file_type]
            canonical_record = json.dumps(
                self.record_data, sort_keys=True, separators=(",", ":")
            ).encode("utf-8")
            content_hash = hashlib.sha256(canonical_record).hexdigest()
            record_id = hashlib.sha256(
                f"{self.uploaded_by.lower()}:{content_hash}".encode("utf-8")
            ).hexdigest()
            doc_id = f"brainstem-record:{record_id}"
            c = CreateBrainStemEntityCommand(
                self.uploaded_by,
                relative_filepath,
                brainstem_file_type,
                "json",
                filename,
                document_id=doc_id,
                record_data=self.record_data,
                record_summary=self.record_summary,
                content_hash=content_hash,
            )
            result = c.execute()
            if c.successful:
                self.successful = True
            else:
                self.successful = False
                self.error_status = 500
                self.messages.extend(c.messages or ["Unable to persist Brainstem record"])
        except Exception as e:
            self.successful = False
            self.messages.append(str(e))
        finally:
            if os.path.isfile(file_path):
                os.remove(file_path)
        return result

    def validate_json(self, file_path):
        try:
            with open(file_path, encoding="utf-8") as file:
                self.record_data = json.load(file)
            self.record_summary = parse_record(self.record_data)
            return True
        except (OSError, json.JSONDecodeError, RecordValidationError) as exc:
            self.messages.append(str(exc))
            return False
