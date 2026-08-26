from types import SimpleNamespace

from commands.metadata import upload_record_command as upload_module
from commands.metadata.upload_record_command import UploadRecordCommand


class Users:
    def __init__(self, usage="UNKNOWN", guidelines="UNKNOWN"):
        self.user = {
            "usage_flag": usage,
            "guidelines_acceptance_flag": guidelines,
        }

    def get_by_public_address(self, _address):
        return {"result": [self.user]}


def command(monkeypatch, users):
    monkeypatch.setattr(upload_module, "user_dao", users)
    monkeypatch.setattr(upload_module.os.path, "exists", lambda _path: True)
    monkeypatch.setattr(upload_module.os, "unlink", lambda _path: None)
    upload = UploadRecordCommand(
        SimpleNamespace(filename="record.json", save=lambda _path: None),
        "0x" + "1" * 40,
    )
    monkeypatch.setattr(upload, "validate_json", lambda _path: False)
    upload.execute()
    return upload


def test_legacy_unknown_user_reaches_record_validation(monkeypatch):
    upload = command(monkeypatch, Users())

    assert upload.error_status == 400
    assert upload.messages == []


def test_explicit_rejection_still_blocks_before_file_handling(monkeypatch):
    upload = command(monkeypatch, Users(usage="REJECTED"))

    assert upload.error_status == 403
    assert upload.messages == ["Brainstem data consent is required"]
