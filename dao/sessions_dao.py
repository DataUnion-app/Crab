from config import config
from dao.base_dao import BaseDao, DBResultError
from datetime import datetime
from utils.get_random_string import get_random_string


MAX_ACTIVE_PARTICIPANT_CHALLENGES = 4


class ParticipantSessionStateError(Exception):
    pass


class SessionsDao(BaseDao):
    def add_to_blacklist(self, jti):
        doc_id = get_random_string()
        self.save(
            doc_id,
            {
                "jti": jti,
                "black_listed": True,
                "created_at": datetime.timestamp(datetime.now()),
            },
        )

    def is_blacklisted(self, jti):
        selector = {"selector": {"_id": {"$gt": None}, "jti": jti}}
        result = self.query_data(selector)["result"]
        if len(result) == 1:
            return True
        return False

    @staticmethod
    def _challenge_doc_id(slot):
        return "participant_challenges:{}".format(slot)

    def create_participant_challenge(self, slot, data, now):
        doc_id = self._challenge_doc_id(slot)
        initial = {
            "document_type": "participant_auth_challenges",
            "slot": slot,
            "challenges": {data["challenge_id"]: data},
        }
        exists, _current = self.get_if_exists(doc_id)
        if not exists:
            try:
                self.save(doc_id, initial)
                return data
            except DBResultError:
                exists, _current = self.get_if_exists(doc_id)
                if not exists:
                    raise

        def add(document):
            challenges = document.get("challenges")
            if not isinstance(challenges, dict) or document.get("slot") != slot:
                raise ParticipantSessionStateError("Challenge storage unavailable")
            challenges = {
                challenge_id: challenge
                for challenge_id, challenge in challenges.items()
                if isinstance(challenge, dict)
                and challenge.get("expires_at", 0) > now
            }
            if len(challenges) >= MAX_ACTIVE_PARTICIPANT_CHALLENGES:
                raise ParticipantSessionStateError("Challenge capacity reached")
            challenges[data["challenge_id"]] = data
            document["challenges"] = challenges
            return document

        self.mutate_doc(doc_id, add)
        return data

    def consume_participant_challenge(self, slot, challenge_id, now):
        doc_id = self._challenge_doc_id(slot)

        def consume(document):
            challenges = document.get("challenges")
            challenge = (
                challenges.get(challenge_id)
                if isinstance(challenges, dict)
                else None
            )
            if not isinstance(challenge, dict):
                raise ParticipantSessionStateError("Challenge unavailable")
            if challenge.get("expires_at", 0) <= now:
                raise ParticipantSessionStateError("Challenge expired")
            challenges.pop(challenge_id)
            return document

        return self.mutate_doc(doc_id, consume)

    def get_participant_challenge(self, slot, challenge_id):
        exists, document = self.get_if_exists(self._challenge_doc_id(slot))
        if not exists:
            raise ParticipantSessionStateError("Challenge unavailable")
        challenges = document.get("challenges")
        challenge = (
            challenges.get(challenge_id) if isinstance(challenges, dict) else None
        )
        if not isinstance(challenge, dict):
            raise ParticipantSessionStateError("Challenge unavailable")
        return challenge

    def create_or_replace_participant_session(self, session_id, data):
        doc_id = "participant_session:{}".format(session_id)
        exists, current = self.get_if_exists(doc_id)
        if exists:
            data["_rev"] = current["_rev"]
        self.save(doc_id, data)

    def get_participant_session(self, session_id):
        exists, document = self.get_if_exists(
            "participant_session:{}".format(session_id)
        )
        if not exists:
            raise ParticipantSessionStateError("Participant session unavailable")
        return document

    def revoke_participant_session(self, session_id, now):
        doc_id = "participant_session:{}".format(session_id)

        def revoke(document):
            if document.get("revoked_at") is None:
                document["revoked_at"] = now
            return document

        return self.mutate_doc(doc_id, revoke)


sessions_dao = SessionsDao()
sessions_dao.set_config(
    config["couchdb"]["user"],
    config["couchdb"]["password"],
    config["couchdb"]["db_host"],
    config["couchdb"]["sessions_db"],
)
