import os
from pathlib import Path

from commands.base_command import BaseCommand
from commands.dataunions.brainstem.record_projection import (
    rebuild_brainstem_record_projection,
)
from config import config
from dao.metadata_dao import image_metadata_dao
from dao.rewards_dao import rewards_dao
from dao.users_dao import user_dao
from models.metadata.metadata_models import Source


class DeleteRecordsCommand(BaseCommand):
    def __init__(
        self,
        uploaded_by: str,
        metadata_dao=None,
        users_dao=None,
        reward_dao=None,
        upload_root=None,
    ):
        super().__init__()
        self.uploaded_by = uploaded_by
        self.image_metadata_dao = metadata_dao or image_metadata_dao
        self.users_dao = users_dao or user_dao
        self.rewards_dao = reward_dao or rewards_dao
        self.source = Source.brainstem
        self.file_type = "record"
        configured_root = upload_root or config["application"].get(
            "upload_folder", "data"
        )
        self.upload_root = Path(configured_root)
        if not self.upload_root.is_absolute():
            self.upload_root = Path.cwd() / self.upload_root

    def _local_path(self, document):
        stored_path = document.get("file_path")
        if not isinstance(stored_path, str) or not stored_path:
            raise ValueError("Record file path is invalid")
        candidate = Path(stored_path)
        if not candidate.is_absolute():
            candidate = Path.cwd() / candidate
        upload_root = self.upload_root.resolve()
        root = (upload_root / self.uploaded_by).resolve()
        try:
            root.relative_to(upload_root)
        except ValueError as exc:
            raise ValueError("Record owner path is outside the upload root") from exc
        if candidate.is_symlink():
            raise ValueError("Record file path must not be a symlink")
        resolved_parent = candidate.parent.resolve(strict=False)
        try:
            resolved_parent.relative_to(root)
        except ValueError as exc:
            raise ValueError("Record file path is outside the owner upload root") from exc
        return candidate

    def _remaining_documents(self):
        return self.image_metadata_dao.query_all({
            "selector": {
                "created_by": self.uploaded_by,
                "file_type": self.file_type,
            }
        })

    def _repair_user_projection(self, remaining_documents):
        users = self.users_dao.get_by_public_address(self.uploaded_by).get(
            "result", []
        )
        if len(users) != 1:
            raise ValueError("Brainstem user was not found uniquely")
        user_id = users[0]["_id"]
        self.users_dao.mutate_doc(
            user_id,
            lambda current: rebuild_brainstem_record_projection(
                current, remaining_documents
            ),
        )

    def execute(self):
        query = {
            "selector": {
                "created_by": self.uploaded_by,
                "file_type": self.file_type,
            }
        }
        documents = self.image_metadata_dao.query_all(query)
        for document in documents:
            try:
                if document.get("storage"):
                    raise ValueError("Non-local record deletion is not supported")
                file_path = self._local_path(document)
                try:
                    os.unlink(file_path)
                except FileNotFoundError:
                    pass
                self.image_metadata_dao.delete_doc(document["_id"])
            except Exception as exc:
                self.messages.append(str(exc))

        try:
            remaining_documents = self._remaining_documents()
            self.rewards_dao.void_orphaned_brainstem_eligibilities(
                self.uploaded_by,
                [document["_id"] for document in remaining_documents],
            )
            self._repair_user_projection(remaining_documents)
        except Exception as exc:
            self.messages.append(str(exc))

        self.successful = not self.messages
        return None
