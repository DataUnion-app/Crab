from enum import Enum


class EntityListType(str, Enum):
    PUBLIC = "public"
    PRIVATE = "private"
    BOUNTY = "bounty"
