from config import config
from dao.base_dao import BaseDao


class CohortReleaseDao(BaseDao):
    pass


cohort_release_dao = CohortReleaseDao()
cohort_release_dao.set_config(
    config["couchdb"]["user"],
    config["couchdb"]["password"],
    config["couchdb"]["db_host"],
    config["couchdb"].get("cohort_releases_db", "cohort_releases"),
)
