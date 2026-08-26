from enum import Enum
from typing import Union


class EntityType(str, Enum):
    image = "image"
    video = "video"
    json = "json"
    text = "text"
    tutorial = "tutorial"
    referral = "referral"

    @staticmethod
    def from_str(label):
        if label == 'image':
            return EntityType.image
        elif label == "video":
            return EntityType.video
        elif label == "json":
            return EntityType.json
        elif label == "text":
            return EntityType.text
        elif label == "tutorial":
            return EntityType.tutorial
        elif label == "referral":
            return EntityType.referral
        else:
            raise NotImplementedError


class EntitySubType(str, Enum):
    # Wedatanation entity

    facebook = "facebook"
    amazon = "amazon"
    netflix = "netflix"
    zalando = "zalando"
    spotify = "spotify"
    web3 = "web3"
    google = "google"
    linkedin = "linkedin"
    linkedin_part_1 = "linkedin_part_1"
    linkedin_part_2 = "linkedin_part_2"

    twitter = "twitter"
    user_metadata = "user_metadata"
    survey = "survey"

    # Brainstem entity
    summary = "summary"
    over_chunk = "over_chunk"
    hbr_rr = "hbr_rr"
    heartbeat = "heartbeat"
    data_share="data_share"
    record="record"


class Network(str, Enum):
    eth_mainnet = "eth_mainnet"
    polygon_mainnet = "polygon_mainnet"
    default = None

    @classmethod
    def _missing_(cls, value):
        return cls.default


class MonetizationStatus(str, Enum):
    enabled = "enabled"
    disabled = "disabled"


class Source(str, Enum):
    wedatanation = "wedatanation"
    dataunion = "dataunion"
    default = None
    brainstem = "brainstem"
    other = "other"
    ncight = "ncight"
    cvat = "cvat"
    recyclium = "recyclium"
    icehockey = "icehockey"

    @classmethod
    def _missing_(cls, value):
        return cls.default


class FileLocation(str, Enum):
    server = "server"
    database_file = "database_file"


class EntityRewardStatus(str, Enum):
    unpaid = "unpaid"
    paid = "paid"

class QRCodeStatus(str, Enum):
    created = "created"
    active = "active"
    scanned = "scanned"
    collected = "collected"
    stored = "stored"
    transport = "transport"
    qualitycheck = "qualitycheck"
    returned = "returned"
    recycled = "recycled"

class QRCodeType(str, Enum):
    general = "general"
    aggregated = "aggregated"

class CSVStatus(str, Enum):
    accepted = "Accepted"
    rejected = "Rejected"

class ReportType(str, Enum):
    pdf = "pdf"
    csv = "csv"
