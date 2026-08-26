from enum import Enum


class MissionType(str, Enum):
    UPLOAD = 'upload'
    ANNOTATE = 'annotate'
    VERIFY = 'verify'

    @staticmethod
    def from_str(label):
        if label == 'upload':
            return MissionType.UPLOAD
        elif label == "annotate":
            return MissionType.ANNOTATE
        elif label == "verify":
            return MissionType.VERIFY
        else:
            raise NotImplementedError

    @staticmethod
    def list():
        return list(map(lambda c: c.value, MissionType))


class MissionStatus(str, Enum):
    READY_TO_START = 'ready_to_start'
    IN_PROGRESS = 'in_progress'
    COMPLETED = 'completed'

    @staticmethod
    def from_str(label):
        if label == 'in_progress':
            return MissionStatus.IN_PROGRESS
        elif label == "completed":
            return MissionStatus.COMPLETED
        elif label == "ready_to_start":
            return MissionStatus.READY_TO_START
        else:
            raise NotImplementedError

    @staticmethod
    def list():
        return list(map(lambda c: c.value, MissionStatus))


class MissionRewardStatus(str, Enum):
    paid = "paid"
    ready_to_pay = "ready_to_pay"
    not_ready_to_be_paid = "not_ready_to_be_paid"
