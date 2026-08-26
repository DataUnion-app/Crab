from enum import Enum


class ImageStatus(Enum):
    NEW = (1,)
    AVAILABLE_FOR_TAGGING = (2,)
    VERIFIABLE = (3,)
    VERIFIED = (4,)
    PUBLISHED = (6,)
    MISSING_FILE = (8,)
    REPORTED_AS_INAPPROPRIATE = 9
