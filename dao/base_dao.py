import abc
import json
import logging
from copy import deepcopy
from typing import List, Any

from requests import Response

from config import config
from dao.couchdb_client import CouchDBClient
from utils.get_random_string import get_random_string


class BaseDao(metaclass=abc.ABCMeta):
    user = None
    password = None
    db_host = None
    db_name = None
    base_url = None
    client = None
    _instance = None
    id_prefix = ''

    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            cls._instance = super(BaseDao, cls).__new__(cls, *args, **kwargs)
        return cls._instance

    def __init__(self):
        self.page_size = 100

    def set_config(self, user, password, db_host, db_name):
        self.user = user
        self.password = password
        self.db_host = db_host
        self.db_name = db_name
        self.client = CouchDBClient(
            user,
            password,
            db_host,
            connect_timeout=config["couchdb"].getfloat(
                "connect_timeout_seconds", fallback=3.05
            ),
            read_timeout=config["couchdb"].getfloat(
                "read_timeout_seconds", fallback=30
            ),
        )
        self.base_url = self.client.database_url(self.db_name)

    def save(self, doc_id: str, data: dict):
        url = self.client.document_url(self.db_name, doc_id)
        headers = {"Content-Type": "application/json"}

        response = self.client.request("PUT", url, headers=headers, data=json.dumps(data))
        if response.status_code not in [201, 200]:
            raise DBResultError(self.db_name, response.text)

        return json.loads(response.text)

    def get_all(self):
        documents = self.query_all()
        return {"result": documents}

    def get_doc_by_id(self, doc_id):
        url = self.client.document_url(self.db_name, doc_id)
        headers = {"Accept": "application/json"}
        response = self.client.request("GET", url, headers=headers)
        data = json.loads(response.text)

        if response.status_code != 200:
            raise DBResultError(self.db_name, response.text)

        return data

    def query_data(self, selector):
        headers = {"Content-Type": "application/json"}
        url = f"{self.base_url}/_find"
        response = self.client.request(
            "POST", url, headers=headers, data=json.dumps(selector)
        )
        if response.status_code != 200:
            logging.info(
                "Failed to query data from db [%s]. Reason [%s]",
                self.db_name,
                response.text.rstrip(),
            )
            raise DBResultError(self.db_name, response.text)
        try:
            data = json.loads(response.text).get("docs")
            return {"result": data}
        except ValueError:
            return {"result": []}

    def update_doc(self, doc_id, data):
        return self.save(doc_id, data)

    def mutate_doc(self, doc_id, mutator, max_attempts=3):
        """Reread and recompute a document mutation after CouchDB conflicts."""
        url = self.client.document_url(self.db_name, doc_id)
        for _attempt in range(max_attempts):
            response = self.client.request("GET", url)
            if response.status_code != 200:
                raise DBResultError(self.db_name, response.text)
            current = response.json()
            updated = mutator(deepcopy(current))
            if updated is None:
                return current
            response = self.client.request(
                "PUT",
                url,
                headers={"Content-Type": "application/json"},
                data=json.dumps(updated),
            )
            if response.status_code in {200, 201}:
                return response.json()
            if response.status_code != 409:
                raise DBResultError(self.db_name, response.text)
        raise DBConflictError(self.db_name, doc_id, max_attempts)

    def delete_db(self):
        logging.debug("Deleting db [%s]", self.db_name)
        url = self.base_url
        payload = {}
        headers = {}
        self.client.request("DELETE", url, headers=headers, data=payload)

    def delete_all_docs(self):
        logging.debug("Deleting all docs in db [%s]", self.db_name)
        doc_ids = self.get_all_doc_id()

        to_delete = []
        for doc in doc_ids:
            # self.delete_doc(doc["id"])
            to_delete.append({"_deleted": True, "_id": doc["id"], "_rev": doc["rev"]})

        url = f"{self.base_url}/_bulk_docs"
        response = self.client.request("POST", url, json={"docs": to_delete})
        logging.debug(
            "Response for delete all docs [%s] is [%s]",
            self.db_name,
            response.status_code,
        )

    def create_db(self):
        logging.debug("Creating db [%s]", self.db_name)
        url = self.base_url
        payload = {}
        headers = {}
        response = self.client.request("PUT", url, headers=headers, data=payload)
        if response.status_code == 201:
            return True
        return False

    def exists(self, doc_id):
        url = self.client.document_url(self.db_name, doc_id)
        headers = {"Accept": "application/json"}
        response = self.client.request("GET", url, headers=headers)
        if response.status_code == 200:
            return True
        return False

    def get_if_exists(self, doc_id) -> tuple:
        url = self.client.document_url(self.db_name, doc_id)
        headers = {"Accept": "application/json"}
        response = self.client.request("GET", url, headers=headers)

        if response.status_code == 200:
            return True, response.json()
        if response.status_code == 404:
            return False, None
        raise DBResultError(self.db_name, response.text)

    def check_if_exists(self, doc_id):
        url = self.client.document_url(self.db_name, doc_id)
        headers = {"Accept": "application/json"}
        response = self.client.request("HEAD", url, headers=headers)
        if response.status_code == 200:
            return True
        return False

    def get_all_doc_id(self):
        all_docs_url = f"{self.base_url}/_design/all-docs/_view/all-docs"
        payload = {}
        headers = {"Content-Type": "application/json"}
        response = self.client.request("GET", all_docs_url, headers=headers, data=payload)

        if response.status_code != 200:
            raise DBResultError(self.db_name, response.text)

        data = json.loads(response.text)["rows"]
        doc_ids = [
            {"id": doc["value"]["id"], "rev": doc["value"]["rev"]} for doc in data
        ]
        return doc_ids

    def delete_doc(self, doc_id):

        document = self.get_doc_by_id(doc_id)
        revision = document["_rev"]
        url = f"{self.client.document_url(self.db_name, doc_id)}?rev={revision}"
        payload = {}
        headers = {}
        response = self.client.request("DELETE", url, headers=headers, data=payload)
        if response.status_code != 200:
            raise DBResultError(self.db_name, response.text)

    def query_all(self, selector: object = None) -> List[object]:
        if selector is None:
            selector = {"selector": {"_id": {"$gt": None}}}
        skip = 0
        limit = 10 ** 6
        docs = []
        while True:
            selector["skip"] = skip
            selector["limit"] = limit
            result = self.query_data(selector)["result"]
            docs = docs + result
            if len(result) == 0:
                break
            skip = skip + limit
        return docs

    def iter_query(self, selector: object, batch_size: int = 500):
        """Yield Mango results in bounded bookmark pages."""
        query = deepcopy(selector)
        query["limit"] = batch_size
        bookmark = None
        while True:
            if bookmark:
                query["bookmark"] = bookmark
            response = self.client.request(
                "POST",
                f"{self.base_url}/_find",
                headers={"Content-Type": "application/json"},
                data=json.dumps(query),
            )
            if response.status_code != 200:
                raise DBResultError(self.db_name, response.text)
            payload = response.json()
            documents = payload.get("docs", [])
            for document in documents:
                yield document
            next_bookmark = payload.get("bookmark")
            if not documents or not next_bookmark or next_bookmark == bookmark:
                break
            bookmark = next_bookmark

    def generate_new_doc_id(self) -> str:
        if self.id_prefix:
            return self.id_prefix + ':' + get_random_string(15)
        return get_random_string(15)

    def get_document_rev(self, doc_id) -> str:
        document = self.get_doc_by_id(doc_id)
        revision = document["_rev"]
        return revision

    def save_attachment(self, file_name, file_path, doc_id, content_type) -> bool:
        with open(file_path, "rb") as img:
            rev = self.get_document_rev(doc_id)
            url = f"{self.base_url}/{doc_id}/{file_name}?rev={rev}"
            headers = {
                'Content-Type': content_type
            }
            response = self.client.request("PUT", url, headers=headers, data=img)
            if response.status_code != 201:
                return False
        return True

    def get_attachment(self, doc_id: str, attachment_name: str) -> Response:
        url = f"{self.base_url}/{doc_id}/{attachment_name}"
        response = self.client.request("GET", url, headers={}, data={})
        if response.status_code != 200:
            raise DBResultError(self.db_name, response.text)
        return response

    def query_view_by_keys(self, design_doc: str, view_name: str, keys: List[Any]) -> Any:

        keys = "[" + ",".join(keys) + "]"
        url = f"{self.base_url}/_design/{design_doc}/_view/{view_name}?keys={keys}"

        response = self.client.request("GET", url, headers={}, data={})
        print("---data---", url)
        if response.status_code != 200:
            raise DBResultError(self.db_name, response.text)

        return json.loads(response.text)

    def query_view(self, design_doc: str, view_name: str, skip: int = 0, limit: int = 1000000,
                   attachments: bool = False, include_docs: bool = False, group: bool = False) -> Any:
        a = "false" if attachments is False else "true"
        b = "false" if include_docs is False else "true"
        c = "false" if group is False else "true"

        url = f"{self.base_url}/_design/{design_doc}/_view/{view_name}?skip={skip}&limit={limit}&attachments={a}&include_docs={b}&group={c}"

        response = self.client.request("GET", url, headers={}, data={})
        if response.status_code != 200:
            raise DBResultError(self.db_name, response.text)

        return json.loads(response.text)

    def query_view_by_key_range(
        self,
        design_doc: str,
        view_name: str,
        start_key: Any,
        end_key: Any,
        group_level: int = None,
        skip: int = 0,
        limit: int = 1000000,
        reduce: bool = True,
        group: bool = False,
        sort_direction: str = None,
        include_docs: bool = False
    ) -> Any:

        url = f"{self.base_url}/_design/{design_doc}/_view/{view_name}?skip={skip}&limit={limit}"

        if group_level is not None:
            url += f"&group_level={group_level}"
        if not reduce:
            url += "&reduce=false"
        if group:
            url += "&group=true"
        if sort_direction == "descending":
            url += "&descending=true"
            if start_key is not None:
                url += f"&start_key={json.dumps(end_key)}"
            if end_key is not None:
                url += f"&end_key={json.dumps(start_key)}"
        elif sort_direction == "ascending":
            url += "&descending=false"
            if start_key is not None:
                url += f"&start_key={json.dumps(start_key)}"
            if end_key is not None:
                url += f"&end_key={json.dumps(end_key)}"
        else:
            if start_key is not None:
                url += f"&start_key={json.dumps(start_key)}"
            if end_key is not None:
                url += f"&end_key={json.dumps(end_key)}"
        if include_docs:
            url += "&include_docs=true"

        response = self.client.request("GET", url, headers={})

        if response.status_code != 200:
            raise DBResultError(self.db_name, response.text)

        return response.json()


class DBResultError(Exception):
    def __init__(self, db_name: str, message: str):
        self.message = message
        self.db_name = db_name
        super().__init__(self.message)

    def __str__(self):
        return f'[{self.db_name}]:{self.message}'


class DBConflictError(DBResultError):
    def __init__(self, db_name, doc_id, attempts):
        super().__init__(
            db_name,
            f"Document conflict for [{doc_id}] after [{attempts}] attempts",
        )
