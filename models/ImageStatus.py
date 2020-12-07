from enum import Enum


class ImageStatus(Enum):
    NEW = 1,
    VERIFIED = 2,
    UNVERIFIED = 3,
    TAGGING = 4,
    READY_TO_PUBLISH = 4,
    PUBLISHED = 5,
    UNPUBLISHED = 6,
    MISSING_FILE = 7
