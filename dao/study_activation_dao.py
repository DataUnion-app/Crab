import hashlib
import hmac
import json

from config import config
from dao.base_dao import BaseDao, DBResultError


MAX_ACTIVE_CHALLENGES = 4
MAX_CHALLENGE_HISTORY = 80
MAX_PERMITS = 40
MAX_DATA_CHALLENGES = 80
MAX_DATA_PERMITS = 40


class StudyActivationStateError(RuntimeError):
    pass


class StudyActivationDao(BaseDao):
    @staticmethod
    def _doc_id(proposal_id):
        return "study_activation:{}".format(proposal_id)

    def create_challenge(self, proposal_id, challenge, now):
        doc_id = self._doc_id(proposal_id)
        initial = {
            "document_type": "brainstem_study_activation",
            "proposal_id": proposal_id,
            "challenges": {challenge["challenge_id"]: challenge},
            "permits": {},
        }
        exists, _current = self.get_if_exists(doc_id)
        if not exists:
            try:
                self.save(doc_id, initial)
                return challenge
            except DBResultError:
                exists, _current = self.get_if_exists(doc_id)
                if not exists:
                    raise

        def add(document):
            if (
                document.get("document_type") != "brainstem_study_activation"
                or document.get("proposal_id") != proposal_id
                or not isinstance(document.get("challenges"), dict)
                or not isinstance(document.get("permits"), dict)
            ):
                raise StudyActivationStateError("Activation storage unavailable")
            active = [
                value
                for value in document["challenges"].values()
                if isinstance(value, dict)
                and value.get("consumed_at") is None
                and value.get("expires_at", 0) > now
            ]
            if len(active) >= MAX_ACTIVE_CHALLENGES:
                raise StudyActivationStateError("Activation challenge capacity reached")
            expired_unused = sorted(
                (
                    value
                    for value in document["challenges"].values()
                    if isinstance(value, dict)
                    and value.get("consumed_at") is None
                    and value.get("expires_at", 0) <= now
                ),
                key=lambda value: value.get("issued_at", 0),
            )
            while len(document["challenges"]) >= MAX_CHALLENGE_HISTORY and expired_unused:
                expired = expired_unused.pop(0)
                document["challenges"].pop(expired.get("challenge_id"), None)
            if len(document["challenges"]) >= MAX_CHALLENGE_HISTORY:
                raise StudyActivationStateError("Activation challenge capacity reached")
            document["challenges"][challenge["challenge_id"]] = challenge
            return document

        self.mutate_doc(doc_id, add)
        return challenge

    def get_challenge(self, proposal_id, challenge_id):
        exists, document = self.get_if_exists(self._doc_id(proposal_id))
        challenge = (
            document.get("challenges", {}).get(challenge_id) if exists else None
        )
        if not isinstance(challenge, dict):
            raise StudyActivationStateError("Activation challenge unavailable")
        return challenge

    def consume_challenge_and_create_permit(
        self,
        proposal_id,
        challenge_id,
        expected_bundle_sha256,
        permit,
        signature,
        now,
    ):
        result = {}

        def consume(document):
            challenges = document.get("challenges")
            permits = document.get("permits")
            challenge = (
                challenges.get(challenge_id) if isinstance(challenges, dict) else None
            )
            if not isinstance(challenge, dict) or not isinstance(permits, dict):
                raise StudyActivationStateError("Activation challenge unavailable")
            if challenge.get("consumed_at") is not None:
                raise StudyActivationStateError("Activation challenge already used")
            if type(challenge.get("expires_at")) is not int:
                raise StudyActivationStateError("Activation challenge unavailable")
            if challenge["expires_at"] <= now:
                raise StudyActivationStateError("Activation challenge expired")
            stored_bundle_sha256 = challenge.get("bundle_sha256")
            if (
                not isinstance(stored_bundle_sha256, str)
                or not isinstance(expected_bundle_sha256, str)
                or not hmac.compare_digest(
                    stored_bundle_sha256, expected_bundle_sha256
                )
            ):
                raise StudyActivationStateError("Activation bundle changed")
            if len(permits) >= MAX_PERMITS or permit["permitId"] in permits:
                raise StudyActivationStateError("Activation permit capacity reached")
            permits[permit["permitId"]] = permit
            challenge["consumed_at"] = now
            challenge["permit_id"] = permit["permitId"]
            challenge["signature_sha256"] = hashlib.sha256(
                signature.encode("ascii")
            ).hexdigest()
            challenge["signature"] = signature
            result.update(permit)
            return document

        self.mutate_doc(self._doc_id(proposal_id), consume)
        return result

    def get_permit(self, proposal_id, permit_id):
        exists, document = self.get_if_exists(self._doc_id(proposal_id))
        permit = document.get("permits", {}).get(permit_id) if exists else None
        if not isinstance(permit, dict):
            raise StudyActivationStateError("Activation permit unavailable")
        return permit

    def get_permit_evidence(self, proposal_id, permit_id):
        exists, document = self.get_if_exists(self._doc_id(proposal_id))
        permit = document.get("permits", {}).get(permit_id) if exists else None
        challenge_id = permit.get("challengeId") if isinstance(permit, dict) else None
        challenge = (
            document.get("challenges", {}).get(challenge_id) if exists else None
        )
        if not isinstance(permit, dict) or not isinstance(challenge, dict):
            raise StudyActivationStateError("Activation permit evidence unavailable")
        return {"permit": permit, "challenge": challenge}

    def create_data_challenge(self, proposal_id, challenge, now):
        def add(document):
            challenges = document.setdefault("data_challenges", {})
            document.setdefault("data_permits", {})
            document.setdefault("data_receipts", {})
            active = [
                item
                for item in challenges.values()
                if isinstance(item, dict)
                and item.get("consumed_at") is None
                and item.get("expires_at", 0) > now
            ]
            if len(active) >= MAX_ACTIVE_CHALLENGES:
                raise StudyActivationStateError("Data action challenge capacity reached")
            expired_unused = sorted(
                (
                    item
                    for item in challenges.values()
                    if isinstance(item, dict)
                    and item.get("consumed_at") is None
                    and item.get("expires_at", 0) <= now
                ),
                key=lambda item: item.get("issued_at", 0),
            )
            while len(challenges) >= MAX_DATA_CHALLENGES and expired_unused:
                expired = expired_unused.pop(0)
                challenges.pop(expired.get("challenge_id"), None)
            if len(challenges) >= MAX_DATA_CHALLENGES:
                raise StudyActivationStateError("Data action challenge capacity reached")
            challenges[challenge["challenge_id"]] = challenge
            return document

        self.mutate_doc(self._doc_id(proposal_id), add)
        return challenge

    def get_data_challenge(self, proposal_id, challenge_id):
        exists, document = self.get_if_exists(self._doc_id(proposal_id))
        challenge = (
            document.get("data_challenges", {}).get(challenge_id) if exists else None
        )
        if not isinstance(challenge, dict):
            raise StudyActivationStateError("Data action challenge unavailable")
        return challenge

    def consume_data_challenge(
        self,
        proposal_id,
        challenge_id,
        expected_binding_sha256,
        permit,
        signature,
        now,
    ):
        result = {}

        def consume(document):
            challenges = document.get("data_challenges", {})
            permits = document.setdefault("data_permits", {})
            challenge = challenges.get(challenge_id)
            if not isinstance(challenge, dict):
                raise StudyActivationStateError("Data action challenge unavailable")
            if challenge.get("consumed_at") is not None:
                raise StudyActivationStateError("Data action challenge already used")
            if challenge.get("expires_at", 0) <= now:
                raise StudyActivationStateError("Data action challenge expired")
            if not hmac.compare_digest(
                challenge.get("binding_sha256", ""), expected_binding_sha256
            ):
                raise StudyActivationStateError("Data action binding changed")
            if len(permits) >= MAX_DATA_PERMITS or permit["permitId"] in permits:
                raise StudyActivationStateError("Data action permit capacity reached")
            challenge["consumed_at"] = now
            challenge["permit_id"] = permit["permitId"]
            challenge["signature"] = signature
            challenge["signature_sha256"] = hashlib.sha256(
                signature.encode("ascii")
            ).hexdigest()
            permits[permit["permitId"]] = permit
            result.update(permit)
            return document

        self.mutate_doc(self._doc_id(proposal_id), consume)
        return result

    def get_data_permit_evidence(self, proposal_id, permit_id):
        exists, document = self.get_if_exists(self._doc_id(proposal_id))
        permit = document.get("data_permits", {}).get(permit_id) if exists else None
        challenge = (
            document.get("data_challenges", {}).get(permit.get("challengeId"))
            if isinstance(permit, dict)
            else None
        )
        if not isinstance(permit, dict) or not isinstance(challenge, dict):
            raise StudyActivationStateError("Data action permit unavailable")
        return {"permit": permit, "challenge": challenge}

    @staticmethod
    def _receipt_sha256(receipt):
        unsigned = {key: value for key, value in receipt.items() if key != "receiptSha256"}
        encoded = json.dumps(unsigned, separators=(",", ":"), sort_keys=True).encode()
        return hashlib.sha256(encoded).hexdigest()

    def claim_data_permit(self, proposal_id, permit_id, action, execution_sha256, now):
        result = {}

        def claim(document):
            permit = document.get("data_permits", {}).get(permit_id)
            receipts = document.setdefault("data_receipts", {})
            if not isinstance(permit, dict) or permit.get("action") != action:
                raise StudyActivationStateError("Data action permit unavailable")
            if permit.get("expiresAt") <= now:
                raise StudyActivationStateError("Data action permit expired")
            if permit_id in receipts:
                raise StudyActivationStateError("Data action permit already used")
            receipt = {
                "schema": "brainstem.study-data-action-receipt/v1",
                "permitId": permit_id,
                "permitSha256": permit["permitSha256"],
                "action": action,
                "bindingSha256": permit["bindingSha256"],
                "executionSha256": execution_sha256,
                "claimedAt": now,
                "completedAt": None,
                "resultSha256": None,
                "receiptSha256": None,
            }
            receipt["receiptSha256"] = self._receipt_sha256(receipt)
            receipts[permit_id] = receipt
            result.update(receipt)
            return document

        self.mutate_doc(self._doc_id(proposal_id), claim)
        return result

    def finalize_data_permit(
        self, proposal_id, permit_id, expected_claim_sha256, result_sha256, now
    ):
        result = {}

        def finalize(document):
            receipt = document.get("data_receipts", {}).get(permit_id)
            if (
                not isinstance(receipt, dict)
                or receipt.get("receiptSha256") != expected_claim_sha256
                or receipt.get("completedAt") is not None
            ):
                raise StudyActivationStateError("Data action claim changed")
            receipt["completedAt"] = now
            receipt["resultSha256"] = result_sha256
            receipt["receiptSha256"] = self._receipt_sha256(receipt)
            result.update(receipt)
            return document

        self.mutate_doc(self._doc_id(proposal_id), finalize)
        return result

    def get_data_receipt(self, proposal_id, receipt_sha256):
        exists, document = self.get_if_exists(self._doc_id(proposal_id))
        if exists:
            for receipt in document.get("data_receipts", {}).values():
                if (
                    isinstance(receipt, dict)
                    and receipt.get("completedAt") is not None
                    and hmac.compare_digest(
                        receipt.get("receiptSha256", ""), receipt_sha256
                    )
                ):
                    return receipt
        raise StudyActivationStateError("Data action receipt unavailable")


study_activation_dao = StudyActivationDao()
study_activation_dao.set_config(
    config["couchdb"]["user"],
    config["couchdb"]["password"],
    config["couchdb"]["db_host"],
    config["couchdb"].get("study_activation_db", "brainstem_study_activation"),
)
