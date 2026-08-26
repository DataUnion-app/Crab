import argparse
import json
import os

from commands.staticdata.create_route_permission_doc import CreateRoutePermissionDocCommand
from config import config
from commands.staticdata.add_words import WordTypes
from commands.whitelist.whitelist_command import WhitelistCommand
from dao.base_dao import DBResultError
from utils.get_project_dir import get_project_root
from helpers.add_words import load_words_from_file
import logging
import sys
from dao.static_data_dao import static_data_dao
from dao.couchdb_client import CouchDBClient

logging.basicConfig(stream=sys.stdout, level=logging.INFO)
parser = argparse.ArgumentParser()
parser.add_argument("-r",
                    "--rebuild_views",
                    type=bool,
                    default=False,
                    action=argparse.BooleanOptionalAction,
                    help="Delete all the views from all the db and create new again.")


class InitiateDB:
    def __init__(self, rebuild_views: bool = False):
        self.user = config["couchdb"]["user"]
        self.password = config["couchdb"]["password"]
        self.db_host = config["couchdb"]["db_host"]
        self.client = CouchDBClient(
            self.user,
            self.password,
            self.db_host,
            config["couchdb"].getfloat("connect_timeout_seconds", fallback=3.05),
            config["couchdb"].getfloat("read_timeout_seconds", fallback=30),
        )
        self.rebuild_views = rebuild_views

    def init(self):
        self.create_users_db()
        self.create_sessions_db()
        self.create_metadata_db()
        self.create_static_data_db()
        self.create_taxonomy_db()
        self.create_permission_db()
        self.create_challenges_db()
        self.create_rewards_db()
        self.create_data_list_db()
        self.create_incident_db()
        self.create_missions_db()
        self.create_bounty_db()
        self.create_handshake_db()
        self.create_db("_users")
        self.create_others_db()
        self.create_product_db()
        self.create_qrcode_db()
        self.create_csv_db()
        self.create_report_db()
        self.create_batch_db()
        self.create_material_db()
        self.create_device_db()
        self.create_algorithm_proposals_db()
        self.create_cohort_releases_db()
        self.create_studies_db()
        self.create_study_activation_db()
        self.create_study_operations_db()

    def create_db(self, db_name):

        print("Creating [{0}] db".format(db_name))
        url = self.client.database_url(db_name)
        response = self.client.request("PUT", url, headers={}, data=json.dumps({}))
        print(response.text)

    def create_metadata_db(self):
        metadata_db = config["couchdb"]["metadata_db"]
        self.create_db(metadata_db)

        path = os.path.join("helpers", "db_setup", "metadata_views.json")
        self.create_from_file(path, metadata_db)

    def create_algorithm_proposals_db(self):
        database = config["couchdb"].get(
            "algorithm_proposals_db", "algorithm_proposals"
        )
        self.create_db(database)
        path = os.path.join("helpers", "db_setup", "algorithm_proposal_views.json")
        self.create_from_file(path, database)

    def create_cohort_releases_db(self):
        self.create_db(
            config["couchdb"].get("cohort_releases_db", "cohort_releases")
        )

    def create_studies_db(self):
        database = config["couchdb"].get("studies_db", "brainstem_studies")
        self.create_db(database)
        path = os.path.join("helpers", "db_setup", "study_proposal_views.json")
        self.create_from_file(path, database)

    def create_study_activation_db(self):
        self.create_db(
            config["couchdb"].get(
                "study_activation_db", "brainstem_study_activation"
            )
        )

    def create_study_operations_db(self):
        self.create_db(
            config["couchdb"].get(
                "study_operations_db", "brainstem_study_operations"
            )
        )

    def create_incident_db(self):
        incident_db = config["couchdb"]["incident_db"]
        self.create_db(incident_db)

        path = os.path.join("helpers", "db_setup", "incident_views.json")
        self.create_from_file(path, incident_db)

    def create_permission_db(self):
        metadata_db = config["couchdb"]["permission_db"]
        self.create_db(metadata_db)

        whitelist_cmd = WhitelistCommand()
        whitelist_cmd.prepare_whitelist()

    def create_users_db(self):
        users_db = config["couchdb"]["users_db"]
        self.create_db(users_db)
        path = os.path.join("helpers", "db_setup", "user_views.json")
        self.create_from_file(path, users_db)

    def create_from_file(self, file_path, db_name):
        with open(file_path) as json_file:
            data = json.load(json_file)
            self.create_views(db_name, data["views"])
            self.create_indexes(db_name, data["index"])

    def create_taxonomy_db(self):
        taxonomy_db = config["couchdb"]["taxonomy_db"]
        self.create_db(taxonomy_db)

        path = os.path.join("helpers", "db_setup", "taxonomy_views.json")
        self.create_from_file(path, taxonomy_db)

    def create_sessions_db(self):
        sessions_db = config["couchdb"]["sessions_db"]
        self.create_db(sessions_db)
        self.create_view(sessions_db)

    def create_static_data_db(self):
        static_data_db = config["couchdb"]["static_data_db"]
        self.create_db(static_data_db)
        self.create_view(static_data_db)

        path = os.path.join("helpers", "db_setup", "static_data_views.json")
        self.create_from_file(path, static_data_db)

        root = get_project_root()
        file_path1 = os.path.join(
            root, "helpers", "db_setup", "staticdata", "banned_words.txt"
        )
        load_words_from_file(file_path1, WordTypes.BANNED_WORDS)

        file_path2 = os.path.join(
            root, "helpers", "db_setup", "staticdata", "recommended_words.txt"
        )

        c = CreateRoutePermissionDocCommand(True, True)
        c.execute()

        if c.successful:
            logging.info("Created route permission document")
        else:
            logging.error("Failed to create route permission document")

        load_words_from_file(file_path2, WordTypes.RECOMMENDED_WORDS)

        try:
            doc = static_data_dao.get_doc_by_id("wedatanation_apps")
        except DBResultError as e:
            doc = {}
            pass

        path = os.path.join("helpers", "db_setup", "staticdata", "wedatanation_apps.json")
        with open(path) as f:
            apps = json.load(f)["apps"]

        doc["apps"] = apps
        static_data_dao.update_doc("wedatanation_apps", doc)

    def create_challenges_db(self):
        challenges_db = config["couchdb"]["challenges_db"]
        self.create_db(challenges_db)
        self.create_view(challenges_db)

    def create_missions_db(self):
        missions_db = config["couchdb"]["missions_db"]
        self.create_db(missions_db)
        path = os.path.join("helpers", "db_setup", "mission_views.json")
        self.create_from_file(path, missions_db)

    def create_bounty_db(self):
        bounty_db = config["couchdb"]["bounty_db"]
        self.create_db(bounty_db)
        path = os.path.join("helpers", "db_setup", "bounty_views.json")
        self.create_from_file(path, bounty_db)
    
    def create_batch_db(self):
        batch_db = config["couchdb"]["batch_db"]
        self.create_db(batch_db)
        path = os.path.join("helpers", "db_setup", "batch_views.json")
        self.create_from_file(path, batch_db)

    def create_handshake_db(self):
        handshake_db = config["couchdb"]["handshake_db"]
        self.create_db(handshake_db)
        path = os.path.join("helpers", "db_setup", "handshake_views.json")
        self.create_from_file(path, handshake_db)

    def create_rewards_db(self):
        rewards_db = config["couchdb"]["rewards_db"]
        self.create_db(rewards_db)

        path = os.path.join("helpers", "db_setup", "rewards_views.json")
        self.create_from_file(path, rewards_db)

    def create_others_db(self):
        rewards_db = config["couchdb"]["others_db"]
        self.create_db(rewards_db)

        path = os.path.join("helpers", "db_setup", "other_views.json")
        self.create_from_file(path, rewards_db)

    def create_data_list_db(self):
        data_list_db = config["couchdb"]["entity_list_db"]
        self.create_db(data_list_db)

        path = os.path.join("helpers", "db_setup", "entity_list_views.json")
        self.create_from_file(path, data_list_db)
    
    def create_product_db(self):
        product_db = config["couchdb"]["product_db"]
        self.create_db(product_db)
        self.create_view(product_db)
    
    def create_qrcode_db(self):
        qrcode_db = config["couchdb"]["qrcode_db"]
        self.create_db(qrcode_db)
        self.create_view(qrcode_db)
    
    def create_csv_db(self):
        csv_db = config["couchdb"]["csv_db"]
        self.create_db(csv_db)
        
        path = os.path.join("helpers", "db_setup", "csv_views.json")
        self.create_from_file(path, csv_db)
    
    def create_report_db(self):
        report_db = config["couchdb"]["report_db"]
        self.create_db(report_db)

        path = os.path.join("helpers", "db_setup", "report_views.json")
        self.create_from_file(path, report_db)

    def create_material_db(self):
        material_db = config["couchdb"]["material_db"]
        self.create_db(material_db)

        path = os.path.join("helpers", "db_setup", "material_views.json")
        self.create_from_file(path, material_db)

    def create_device_db(self):
        device_db = config["couchdb"]["device_db"]
        self.create_db(device_db)

        path = os.path.join("helpers", "db_setup", "device_views.json")
        self.create_from_file(path, device_db)

    def create_view(self, db_name):
        print("Creating all-docs view for [{0}]".format(db_name))
        body = {
            "_id": "_design/all-docs",
            "views": {
                "all-docs": {
                    "map": 'function (doc) {\n  emit(doc._id, {"rev":doc._rev, "id": doc._id});\n}'
                }
            },
            "language": "javascript",
        }

        headers = {"Content-Type": "application/json"}

        url = self.client.database_url(db_name)
        response = self.client.request("POST", url, headers=headers, data=json.dumps(body))
        print(response.text)

    def create_doc_count_view(self, db_name):
        print("Creating doc_count_view for [{0}]".format(db_name))
        body = {
            "_id": "_design/counts",
            "language": "javascript",
            "views": {
                "all": {
                    "map": "function(doc) { emit(null, 1); }",
                    "reduce": "function(keys, values, combine) { return sum(values); }",
                }
            },
        }

        headers = {"Content-Type": "application/json"}
        url = self.client.database_url(db_name)
        response = self.client.request("POST", url, headers=headers, data=json.dumps(body))
        print(response.text)

    def create_views(self, db_name, views):

        if self.rebuild_views:
            logging.info("Rebuilding views: for [%s]", db_name)
            self.delete_all_views(db_name)

        for view in views:
            print("Creating view [{0}] for [{1}]".format(view["_id"], db_name))
            body = dict(view)
            headers = {"Content-Type": "application/json"}
            url = self.client.document_url(db_name, view["_id"])
            current = self.client.request("GET", url, headers=headers)
            if current.status_code == 200:
                body["_rev"] = current.json()["_rev"]
            elif current.status_code != 404:
                raise DBResultError(db_name, current.text)
            response = self.client.request(
                "PUT", url, headers=headers, data=json.dumps(body)
            )
            if response.status_code not in (201, 202):
                raise DBResultError(db_name, response.text)
            print(response.text)

    def get_all_views(self, db_name):
        url = f"{self.client.database_url(db_name)}/_design_docs"
        payload = {}
        headers = {}
        response = self.client.request("GET", url, headers=headers, data=payload)
        data = json.loads(response.text)['rows']
        r = [{"id": row["id"], 'rev': row['value']['rev']} for row in data]
        return r

    def delete_all_views(self, db_name):
        views = self.get_all_views(db_name)
        for view in views:
            self.delete_view(db_name, view['id'], view['rev'])

    def delete_view(self, db_name: str, view_id: str, rev: str):
        url = f"{self.client.document_url(db_name, view_id)}?rev={rev}"
        payload = {}
        headers = {}
        response = self.client.request("DELETE", url, headers=headers, data=payload)
        if response.status_code == 200:
            logging.info("[%s]: Deleted view [%s] with rev [%s]", db_name, view_id, rev)

    def create_indexes(self, db_name: str, indexes: list):

        url = f"{self.client.database_url(db_name)}/_index"

        for index in indexes:
            headers = {"Content-Type": "application/json"}
            logging.info("Creating index [%s] for [%s]", index['name'], db_name)
            response = self.client.request("POST", url, headers=headers, data=json.dumps(index))
            print(response.text)


if __name__ == "__main__":
    args = parser.parse_args()

    db_initiator = InitiateDB(args.rebuild_views)
    db_initiator.init()
