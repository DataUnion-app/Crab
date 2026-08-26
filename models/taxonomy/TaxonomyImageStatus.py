from enum import Enum


class TaxonomyImageStatus(Enum):
    NEW = (1,)
    VERIFIABLE = (3,)
    VERIFIED = (4,)
    MISSING_FILE = (5,)
    REPORTED_AS_INAPPROPRIATE = (6,)
    MISSING_FILE_WHILE_LOAD = (7,)
    SKIPPED = (8,)
    UNKNOWN = 9
