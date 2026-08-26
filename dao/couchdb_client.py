from urllib.parse import quote

import requests


class CouchDBClient:
    """Single owner of CouchDB authentication and network time bounds."""

    def __init__(
        self, user, password, host, connect_timeout=3.05, read_timeout=30,
        session=None,
    ):
        if host.startswith("http://") or host.startswith("https://"):
            self.server_url = host.rstrip("/")
        else:
            self.server_url = f"http://{host.rstrip('/')}"
        self.timeout = (connect_timeout, read_timeout)
        self.session = session or requests.Session()
        self.session.auth = (user, password)
        self.session.headers.update({"Accept": "application/json"})

    def database_url(self, database):
        return f"{self.server_url}/{quote(database, safe='')}"

    def document_url(self, database, document_id):
        return f"{self.database_url(database)}/{quote(document_id, safe=':')}"

    def request(self, method, url, **kwargs):
        kwargs.setdefault("timeout", self.timeout)
        return self.session.request(method, url, **kwargs)
