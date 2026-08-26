from collections import defaultdict

from commands.base_command import BaseCommand
from dao.users_dao import user_dao
from dao.metadata_dao import image_metadata_dao
from dao.others_dao import others_db
from datetime import datetime


class RankUserCommand(BaseCommand):
    def __init__(self):
        super(RankUserCommand, self).__init__()
        self.doc_id = "ncight-user-ranks"

    def execute(self):
        exists, doc = others_db.get_if_exists(self.doc_id)
        if not exists:
            doc = {"created_at": datetime.utcnow().isoformat(), "iteration-count": 0}
            others_db.save(self.doc_id, doc)

        result = defaultdict(lambda: defaultdict(dict))
        referrals = user_dao.query_view("counts", "referrals")['rows']
        for r in referrals:
            result[r["key"]]["referrals"] = r["value"]

        uploads = image_metadata_dao.query_view_by_key_range("ncight", "upload-count", None, None, 2)['rows']
        for u in uploads:
            # key = ["public_address", "upload"]
            # value = number
            result[u['key'][0]][u['key'][1]] = u['value']

        classifications = image_metadata_dao.query_view_by_key_range("ncight", "classification-stats", None, None, 1)[
            "rows"]
        for c in classifications:
            '''
            {
            "rows": [
                {
                    "key": "<wallet_address>",
                    "value": {
                        "incorrect_classifications": 2,
                        "correct_classifications": 99,
                        "total_classifications": 101
                    }
                },...
            '''

            total_classifications = c['value']["total_classifications"]
            result[c['key']]["total_classifications"] = total_classifications
            result[c['key']]["classification_accuracy"] = round(
                c['value']["correct_classifications"] / total_classifications * 100, 2)

        r = []

        for k in result.keys():
            r.append({
                'address': k,
                'value': result[k],
                'score': self.get_user_score(referrals=result[k].get('referrals', 0),
                                             uploads=result[k].get('upload', 0),
                                             classification_count=result[k].get('total_classifications', 0),
                                             classification_accuracy=result[k].get('classification_accuracy', 0)),
                "username": user_dao.get_username_by_public_address(k)
            })

        r.sort(key=lambda x: x["score"], reverse=True)
        doc["result"] = r
        doc["iteration-count"] = doc["iteration-count"] + 1
        doc["last_executed_at"] = datetime.utcnow().isoformat()

        others_db.update_doc(self.doc_id, doc)

        self.successful = True
        return doc["result"]

    def get_user_score(self, referrals: int, uploads: int, classification_count: int,
                       classification_accuracy: int) -> float:

        return referrals * 0.55 + uploads * 0.2 + classification_count * 0.3 + classification_accuracy * 0.2


if __name__ == "__main__":
    c = RankUserCommand()
    c.execute()
    assert c.successful
