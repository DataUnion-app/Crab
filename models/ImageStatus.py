from enum import Enum


class ImageStatus(Enum):
    NEW = 1,
    VERIFIED = 2,
    UNVERIFIED = 3,
    AVAILABLE_FOR_TAGGING = 4,
    READY_TO_PUBLISH = 5,
    PUBLISHED = 6,
    UNPUBLISHED = 7,
    MISSING_FILE = 8,
    REPORTED_AS_INAPPROPRIATE = 9
