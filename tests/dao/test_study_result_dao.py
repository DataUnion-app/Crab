import json
import unittest
from unittest.mock import patch

from dao.study_result_dao import StudyResultDao


class Response:
    def __init__(self, status_code):
        self.status_code = status_code
        self.text = ""


class Client:
    def __init__(self):
        self.documents = []

    @staticmethod
    def document_url(_database, document_id):
        return document_id

    def request(self, method, url, **kwargs):
        assert method == "PUT"
        self.documents.append(json.loads(kwargs["data"]))
        return Response(409 if len(self.documents) == 1 else 201)


class StudyResultDaoTest(unittest.TestCase):
    def test_concurrent_version_conflict_retries_with_next_version(self):
        dao = StudyResultDao()
        client = Client()
        prior = [
            {"resultVersion": 1, "resultId": "result_first"},
            {"resultVersion": 2, "resultId": "result_other_job"},
        ]
        gets = iter((None, None))
        lists = iter(([prior[0]], [prior[1]]))
        with (
            patch.object(dao, "client", client),
            patch.object(dao, "db_name", "studies"),
            patch.object(dao, "get", side_effect=lambda *_args: next(gets)),
            patch.object(dao, "list", side_effect=lambda *_args: next(lists)),
        ):
            stored = dao.append(
                {
                    "proposalId": "study_1",
                    "jobIdHash": "a" * 64,
                    "resultId": "result_a",
                    "result": {"status": "complete"},
                }
            )

        self.assertEqual([row["resultVersion"] for row in client.documents], [2, 3])
        self.assertEqual(stored["resultVersion"], 3)
        self.assertEqual(stored["supersedesResultId"], "result_other_job")


if __name__ == "__main__":
    unittest.main()
