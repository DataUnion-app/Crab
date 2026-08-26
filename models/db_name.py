from enum import Enum


class DatabaseName(str, Enum):
    metadata = "metadata"
    bounty = "bounty"
    entity_list = "entity_list"
    static_data = "static_data"
    users = "users"
    other = "other"
    missions = "missions"
    algorithm_proposals = "algorithm_proposals"
