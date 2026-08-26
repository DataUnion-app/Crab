"""Persistent compare-and-set owner for one study operations timeline."""

import hashlib
import hmac

from config import config
from dao.base_dao import BaseDao, DBResultError


MAX_ACTIVE_CHALLENGES = 4
MAX_CHALLENGE_HISTORY = 100
MAX_EVENTS = 100
MAX_PRIVACY_SNAPSHOTS = 400
# The registry rejects activation profiles above this participant ceiling.
# Finalized tickets are durable authority evidence and are never evicted.
MAX_RECRUITMENT_TICKETS = 100000


class StudyOperationsStateError(RuntimeError):
    pass


class StudyOperationsDao(BaseDao):
    @staticmethod
    def _doc_id(proposal_id):
        return "study_operations:{}".format(proposal_id)

    @staticmethod
    def _valid_document(document, proposal_id):
        return (
            isinstance(document, dict)
            and document.get("document_type") == "brainstem_study_operations"
            and document.get("proposal_id") == proposal_id
            and isinstance(document.get("state"), dict)
            and isinstance(document.get("events"), list)
            and isinstance(document.get("challenges"), dict)
            and isinstance(document.get("privacy_snapshots"), list)
            and isinstance(document.get("recruitment_tickets"), dict)
            and (
                document.get("participant_binding_key_id") is None
                or (
                    isinstance(document.get("participant_binding_key_id"), str)
                    and 1 <= len(document["participant_binding_key_id"]) <= 64
                    and document["participant_binding_key_id"].isascii()
                    and all(
                        character.isalnum() or character in "._-"
                        for character in document["participant_binding_key_id"]
                    )
                )
            )
            and (
                document.get("participant_binding_key_commitment_sha256")
                is None
                or (
                    isinstance(
                        document.get(
                            "participant_binding_key_commitment_sha256"
                        ),
                        str,
                    )
                    and len(
                        document[
                            "participant_binding_key_commitment_sha256"
                        ]
                    )
                    == 64
                    and all(
                        character in "0123456789abcdef"
                        for character in document[
                            "participant_binding_key_commitment_sha256"
                        ]
                    )
                )
            )
        )

    def ensure_state(self, proposal_id, initial_state):
        doc_id = self._doc_id(proposal_id)
        exists, document = self.get_if_exists(doc_id)
        if exists:
            if not self._valid_document(document, proposal_id):
                raise StudyOperationsStateError("Study operations storage unavailable")
            return document["state"]
        initial = {
            "document_type": "brainstem_study_operations",
            "proposal_id": proposal_id,
            "state": initial_state,
            "events": [],
            "challenges": {},
            "privacy_snapshots": [],
            "recruitment_tickets": {},
            "participant_binding_key_id": None,
            "participant_binding_key_commitment_sha256": None,
        }
        try:
            self.save(doc_id, initial)
            return initial_state
        except DBResultError:
            exists, document = self.get_if_exists(doc_id)
            if not exists or not self._valid_document(document, proposal_id):
                raise
            return document["state"]

    def get_document(self, proposal_id):
        exists, document = self.get_if_exists(self._doc_id(proposal_id))
        if not exists or not self._valid_document(document, proposal_id):
            raise StudyOperationsStateError("Study operations unavailable")
        return document

    def get_state(self, proposal_id):
        return self.get_document(proposal_id)["state"]

    @staticmethod
    def _recruitment_authority_id(offering_id, release_sha256):
        scope = "{}\0{}".format(offering_id, release_sha256).encode("utf-8")
        return "study_recruitment_authority:{}".format(
            hashlib.sha256(scope).hexdigest()
        )

    @staticmethod
    def _valid_recruitment_authority(authority, offering_id, release_sha256):
        state = authority.get("state") if isinstance(authority, dict) else None
        lease_expires_at = authority.get("lease_expires_at")
        return (
            isinstance(authority, dict)
            and authority.get("document_type")
            == "brainstem_study_recruitment_authority"
            and authority.get("offering_id") == offering_id
            and authority.get("release_sha256") == release_sha256
            and isinstance(authority.get("proposal_id"), str)
            and authority["proposal_id"].startswith("study_")
            and 1 <= len(authority["proposal_id"][6:]) <= 64
            and all(
                character in "0123456789abcdef"
                for character in authority["proposal_id"][6:]
            )
            and isinstance(authority.get("permit_id"), str)
            and authority["permit_id"].startswith("permit_")
            and len(authority["permit_id"]) == 39
            and all(
                character in "0123456789abcdef"
                for character in authority["permit_id"][7:]
            )
            and isinstance(authority.get("claim_id"), str)
            and len(authority["claim_id"]) == 32
            and all(
                character in "0123456789abcdef"
                for character in authority["claim_id"]
            )
            and state in {"pending", "finalized", "released"}
            and (
                (state == "pending" and type(lease_expires_at) is int)
                or (state != "pending" and lease_expires_at is None)
            )
        )

    def get_recruitment_authority(self, offering_id, release_sha256):
        exists, authority = self.get_if_exists(
            self._recruitment_authority_id(offering_id, release_sha256)
        )
        if not exists:
            return None
        if not self._valid_recruitment_authority(
            authority, offering_id, release_sha256
        ):
            raise StudyOperationsStateError(
                "Study recruitment authority unavailable"
            )
        return authority

    def claim_recruitment_authority(
        self,
        offering_id,
        release_sha256,
        proposal_id,
        permit_id,
        claim_id,
        now,
        lease_expires_at,
        replace_claim_id=None,
    ):
        if (
            not isinstance(offering_id, str)
            or not offering_id
            or not isinstance(release_sha256, str)
            or len(release_sha256) != 64
            or any(
                character not in "0123456789abcdef"
                for character in release_sha256
            )
            or not isinstance(proposal_id, str)
            or not proposal_id.startswith("study_")
            or not 1 <= len(proposal_id[6:]) <= 64
            or any(
                character not in "0123456789abcdef"
                for character in proposal_id[6:]
            )
            or not isinstance(permit_id, str)
            or not permit_id.startswith("permit_")
            or len(permit_id) != 39
            or any(
                character not in "0123456789abcdef"
                for character in permit_id[7:]
            )
            or not isinstance(claim_id, str)
            or len(claim_id) != 32
            or any(
                character not in "0123456789abcdef"
                for character in claim_id
            )
            or type(now) is not int
            or type(lease_expires_at) is not int
            or lease_expires_at <= now
        ):
            raise StudyOperationsStateError(
                "Study recruitment authority invalid"
            )
        doc_id = self._recruitment_authority_id(offering_id, release_sha256)
        authority = {
            "document_type": "brainstem_study_recruitment_authority",
            "offering_id": offering_id,
            "release_sha256": release_sha256,
            "proposal_id": proposal_id,
            "permit_id": permit_id,
            "claim_id": claim_id,
            "state": "pending",
            "lease_expires_at": lease_expires_at,
        }
        try:
            self.save(doc_id, authority)
            return authority
        except DBResultError:
            pass

        result = {}

        def claim(existing):
            if not self._valid_recruitment_authority(
                existing, offering_id, release_sha256
            ):
                raise StudyOperationsStateError(
                    "Study recruitment authority unavailable"
                )
            if (
                existing["state"] in {"pending", "finalized"}
                and existing["proposal_id"] == proposal_id
                and existing["permit_id"] == permit_id
                and existing["claim_id"] == claim_id
            ):
                result.update(existing)
                return None
            replace_stale = (
                existing["state"] == "pending"
                and existing["claim_id"] == replace_claim_id
                and existing["lease_expires_at"] <= now
            )
            if existing["state"] != "released" and not replace_stale:
                raise StudyOperationsStateError(
                    "Study recruitment authority already claimed"
                )
            result.update(authority)
            return authority

        try:
            self.mutate_doc(doc_id, claim)
        except DBResultError as error:
            raise StudyOperationsStateError(
                "Study recruitment authority unavailable"
            ) from error
        return result

    def release_recruitment_authority(
        self, offering_id, release_sha256, proposal_id, claim_id
    ):
        def release(authority):
            if not self._valid_recruitment_authority(
                authority, offering_id, release_sha256
            ):
                raise StudyOperationsStateError(
                    "Study recruitment authority unavailable"
                )
            if (
                authority["state"] != "pending"
                or authority["proposal_id"] != proposal_id
                or authority["claim_id"] != claim_id
            ):
                return None
            authority["state"] = "released"
            authority["lease_expires_at"] = None
            return authority

        self.mutate_doc(
            self._recruitment_authority_id(offering_id, release_sha256),
            release,
        )

    def finalize_recruitment_authority(
        self, offering_id, release_sha256, proposal_id, claim_id
    ):
        result = {}

        def finalize(authority):
            if not self._valid_recruitment_authority(
                authority, offering_id, release_sha256
            ):
                raise StudyOperationsStateError(
                    "Study recruitment authority unavailable"
                )
            exact = (
                authority["proposal_id"] == proposal_id
                and authority["claim_id"] == claim_id
            )
            if authority["state"] == "finalized" and exact:
                result.update(authority)
                return None
            if authority["state"] != "pending" or not exact:
                raise StudyOperationsStateError(
                    "Study recruitment authority changed"
                )
            authority["state"] = "finalized"
            authority["lease_expires_at"] = None
            result.update(authority)
            return authority

        self.mutate_doc(
            self._recruitment_authority_id(offering_id, release_sha256),
            finalize,
        )
        return result

    def create_challenge(
        self,
        proposal_id,
        expected_state_sha256,
        challenge,
        now,
    ):
        doc_id = self._doc_id(proposal_id)

        def add(document):
            if not self._valid_document(document, proposal_id):
                raise StudyOperationsStateError("Study operations storage unavailable")
            if document["state"].get("stateSha256") != expected_state_sha256:
                raise StudyOperationsStateError("Study operations state changed")
            for event in document["events"]:
                if event.get("idempotencyKey") == challenge["idempotency_key"]:
                    raise StudyOperationsStateError("Study operation already applied")
            active = [
                value
                for value in document["challenges"].values()
                if isinstance(value, dict)
                and value.get("consumed_at") is None
                and type(value.get("expires_at")) is int
                and value["expires_at"] > now
            ]
            if len(active) >= MAX_ACTIVE_CHALLENGES:
                raise StudyOperationsStateError("Study operation challenge capacity reached")
            removable = sorted(
                (
                    value
                    for value in document["challenges"].values()
                    if isinstance(value, dict)
                    and value.get("consumed_at") is None
                    and (
                        type(value.get("expires_at")) is int
                        and value["expires_at"] <= now
                    )
                ),
                key=lambda value: value.get("issued_at", 0),
            )
            while len(document["challenges"]) >= MAX_CHALLENGE_HISTORY and removable:
                old = removable.pop(0)
                document["challenges"].pop(old.get("challenge_id"), None)
            if len(document["challenges"]) >= MAX_CHALLENGE_HISTORY:
                raise StudyOperationsStateError("Study operation challenge capacity reached")
            document["challenges"][challenge["challenge_id"]] = challenge
            return document

        self.mutate_doc(doc_id, add)
        return challenge

    def get_challenge(self, proposal_id, challenge_id):
        document = self.get_document(proposal_id)
        challenge = document["challenges"].get(challenge_id)
        if not isinstance(challenge, dict):
            raise StudyOperationsStateError("Study operation challenge unavailable")
        return challenge

    def idempotent_result(
        self,
        proposal_id,
        challenge_id,
        expected_bundle_sha256,
    ):
        document = self.get_document(proposal_id)
        challenge = document["challenges"].get(challenge_id)
        if (
            not isinstance(challenge, dict)
            or challenge.get("consumed_at") is None
            or challenge.get("bundle_sha256") != expected_bundle_sha256
        ):
            raise StudyOperationsStateError("Study operation challenge unavailable")
        event_sha256 = challenge.get("event_sha256")
        event = next(
            (
                item
                for item in document["events"]
                if item.get("eventSha256") == event_sha256
            ),
            None,
        )
        if not isinstance(event, dict):
            raise StudyOperationsStateError("Study operation receipt unavailable")
        return {"event": event, "state": document["state"]}

    def consume_transition(
        self,
        proposal_id,
        challenge_id,
        expected_state_sha256,
        expected_bundle_sha256,
        event,
        next_state,
        signature,
        now,
    ):
        result = {}

        def consume(document):
            if not self._valid_document(document, proposal_id):
                raise StudyOperationsStateError("Study operations storage unavailable")
            challenge = document["challenges"].get(challenge_id)
            if not isinstance(challenge, dict):
                raise StudyOperationsStateError("Study operation challenge unavailable")
            if challenge.get("consumed_at") is not None:
                if (
                    challenge.get("bundle_sha256") == expected_bundle_sha256
                    and challenge.get("event_sha256") == event["eventSha256"]
                ):
                    existing = next(
                        (
                            item
                            for item in document["events"]
                            if item.get("eventSha256") == event["eventSha256"]
                        ),
                        None,
                    )
                    if existing is not None:
                        result.update({"event": existing, "state": document["state"]})
                        return None
                raise StudyOperationsStateError("Study operation challenge already used")
            if type(challenge.get("expires_at")) is not int:
                raise StudyOperationsStateError("Study operation challenge unavailable")
            if challenge["expires_at"] <= now:
                raise StudyOperationsStateError("Study operation challenge expired")
            if document["state"].get("stateSha256") != expected_state_sha256:
                raise StudyOperationsStateError("Study operations state changed")
            if not hmac.compare_digest(
                challenge.get("bundle_sha256", ""), expected_bundle_sha256
            ):
                raise StudyOperationsStateError("Study operation bundle changed")
            matching = [
                item
                for item in document["events"]
                if item.get("idempotencyKey") == event["idempotencyKey"]
            ]
            if matching:
                if matching[0].get("eventSha256") != event["eventSha256"]:
                    raise StudyOperationsStateError("Study operation idempotency conflict")
                result.update({"event": matching[0], "state": document["state"]})
                return None
            if len(document["events"]) >= MAX_EVENTS:
                raise StudyOperationsStateError("Study operations event capacity reached")
            for ticket in document["recruitment_tickets"].values():
                if (
                    isinstance(ticket, dict)
                    and ticket.get("finalized_at") is None
                    and ticket.get("cancelled_at") is None
                    and type(ticket.get("expires_at")) is int
                    and ticket["expires_at"] > now
                ):
                    ticket["cancelled_at"] = now
            document["events"].append(event)
            document["state"] = next_state
            challenge["consumed_at"] = now
            challenge["event_sha256"] = event["eventSha256"]
            challenge["signature_sha256"] = hashlib.sha256(
                signature.encode("ascii")
            ).hexdigest()
            challenge["signature"] = signature
            result.update({"event": event, "state": next_state})
            return document

        self.mutate_doc(self._doc_id(proposal_id), consume)
        return result

    def reserve_recruitment(
        self,
        proposal_id,
        expected_state_sha256,
        ticket,
        now,
        maximum_tickets=MAX_RECRUITMENT_TICKETS,
    ):
        result = {}

        def reserve(document):
            if not self._valid_document(document, proposal_id):
                raise StudyOperationsStateError(
                    "Study operations storage unavailable"
                )
            if document["state"].get("stateSha256") != expected_state_sha256:
                raise StudyOperationsStateError("Study operations state changed")
            if (
                type(maximum_tickets) is not int
                or not 1 <= maximum_tickets <= MAX_RECRUITMENT_TICKETS
            ):
                raise StudyOperationsStateError(
                    "Study recruitment reservation capacity invalid"
                )
            tickets = document["recruitment_tickets"]
            key_id = ticket.get("participant_binding_key_id")
            if (
                not isinstance(key_id, str)
                or not 1 <= len(key_id) <= 64
                or not key_id.isascii()
                or not all(
                    character.isalnum() or character in "._-"
                    for character in key_id
                )
            ):
                raise StudyOperationsStateError(
                    "Study recruitment participant binding key invalid"
                )
            if document.get("participant_binding_key_id") is None:
                document["participant_binding_key_id"] = key_id
            elif document["participant_binding_key_id"] != key_id:
                raise StudyOperationsStateError(
                    "Study recruitment participant binding key changed"
                )
            commitment = ticket.get(
                "participant_binding_key_commitment_sha256"
            )
            if (
                not isinstance(commitment, str)
                or len(commitment) != 64
                or any(
                    character not in "0123456789abcdef"
                    for character in commitment
                )
            ):
                raise StudyOperationsStateError(
                    "Study recruitment participant binding key invalid"
                )
            if (
                document.get(
                    "participant_binding_key_commitment_sha256"
                )
                is None
            ):
                document[
                    "participant_binding_key_commitment_sha256"
                ] = commitment
            elif (
                document["participant_binding_key_commitment_sha256"]
                != commitment
            ):
                raise StudyOperationsStateError(
                    "Study recruitment participant binding key changed"
                )
            removable = [
                ticket_id
                for ticket_id, value in tickets.items()
                if isinstance(value, dict)
                and value.get("finalized_at") is None
                and (
                    value.get("cancelled_at") is not None
                    or (
                        type(value.get("expires_at")) is int
                        and value["expires_at"] <= now
                    )
                )
            ]
            for ticket_id in removable:
                tickets.pop(ticket_id, None)
            active = [
                value
                for value in tickets.values()
                if isinstance(value, dict)
                and value.get("finalized_at") is None
                and value.get("cancelled_at") is None
                and type(value.get("expires_at")) is int
                and value["expires_at"] > now
            ]
            existing = next(
                (
                    value
                    for value in active
                    if value.get("reservation_key_sha256")
                    == ticket.get("reservation_key_sha256")
                ),
                None,
            )
            if existing is not None:
                exact = (
                    "proposal_id",
                    "permit_id",
                    "participant_binding_key_id",
                    "participant_binding_key_commitment_sha256",
                    "participant_binding_sha256",
                    "reservation_key_sha256",
                    "operation_state_sha256",
                    "release_sha256",
                    "task_plan_sha256",
                )
                if any(existing.get(key) != ticket.get(key) for key in exact):
                    raise StudyOperationsStateError(
                        "Study recruitment reservation conflict"
                    )
                result.update(existing)
                return document
            if any(
                (
                    value.get("participant_binding_key_id"),
                    value.get("participant_binding_sha256"),
                )
                == (
                    ticket["participant_binding_key_id"],
                    ticket["participant_binding_sha256"],
                )
                for value in active
            ):
                raise StudyOperationsStateError(
                    "Study recruitment participant already reserved"
                )
            occupied = {
                (
                    value.get("participant_binding_key_id"),
                    value.get("participant_binding_sha256"),
                )
                for value in tickets.values()
                if isinstance(value, dict)
                and value.get("finalized_at") is not None
            }
            committed_or_reserved = occupied | {
                (
                    value.get("participant_binding_key_id"),
                    value.get("participant_binding_sha256"),
                )
                for value in active
            }
            participant = (
                ticket["participant_binding_key_id"],
                ticket["participant_binding_sha256"],
            )
            if (
                participant not in committed_or_reserved
                and len(committed_or_reserved) >= maximum_tickets
            ):
                raise StudyOperationsStateError(
                    "Study recruitment reservation capacity reached"
                )
            next_participant_count = len(committed_or_reserved | {participant})
            seats_still_promised = max(
                0, maximum_tickets - next_participant_count
            )
            if (
                len(tickets) + 1 + seats_still_promised
                > MAX_RECRUITMENT_TICKETS
            ):
                raise StudyOperationsStateError(
                    "Study recruitment evidence capacity reached"
                )
            tickets[ticket["ticket_id"]] = ticket
            result.update(ticket)
            return document

        self.mutate_doc(self._doc_id(proposal_id), reserve)
        return result

    def get_recruitment_ticket(self, proposal_id, ticket_id):
        ticket = self.get_document(proposal_id)["recruitment_tickets"].get(
            ticket_id
        )
        if not isinstance(ticket, dict):
            raise StudyOperationsStateError(
                "Study recruitment reservation unavailable"
            )
        return ticket

    def finalize_recruitment(
        self,
        proposal_id,
        ticket_id,
        expected_ticket_sha256,
        enrollment_sha256,
        now,
    ):
        result = {}

        def finalize(document):
            if not self._valid_document(document, proposal_id):
                raise StudyOperationsStateError(
                    "Study operations storage unavailable"
                )
            ticket = document["recruitment_tickets"].get(ticket_id)
            if (
                not isinstance(ticket, dict)
                or ticket.get("ticket_sha256") != expected_ticket_sha256
                or ticket.get("cancelled_at") is not None
            ):
                raise StudyOperationsStateError(
                    "Study recruitment reservation unavailable"
                )
            if ticket.get("finalized_at") is not None:
                if ticket.get("enrollment_sha256") != enrollment_sha256:
                    raise StudyOperationsStateError(
                        "Study recruitment finalization conflict"
                    )
                result.update(ticket)
                return None
            if (
                type(ticket.get("expires_at")) is not int
                or ticket["expires_at"] <= now
                or document["state"].get("stateSha256")
                != ticket.get("operation_state_sha256")
                or document["state"].get("lifecycleState") != "recruiting"
                or document["state"].get("disposition") != "current"
            ):
                raise StudyOperationsStateError(
                    "Study recruitment reservation expired"
                )
            ticket["finalized_at"] = now
            ticket["enrollment_sha256"] = enrollment_sha256
            result.update(ticket)
            return document

        self.mutate_doc(self._doc_id(proposal_id), finalize)
        return result

    def cancel_recruitment(self, proposal_id, ticket_id, now):
        def cancel(document):
            if not self._valid_document(document, proposal_id):
                raise StudyOperationsStateError(
                    "Study operations storage unavailable"
                )
            ticket = document["recruitment_tickets"].get(ticket_id)
            if not isinstance(ticket, dict) or ticket.get("finalized_at") is not None:
                return None
            ticket["cancelled_at"] = now
            return document

        self.mutate_doc(self._doc_id(proposal_id), cancel)

    def cancel_recruitment_reservation(
        self, proposal_id, reservation_key_sha256, now
    ):
        def cancel(document):
            if not self._valid_document(document, proposal_id):
                raise StudyOperationsStateError(
                    "Study operations storage unavailable"
                )
            changed = False
            for ticket in document["recruitment_tickets"].values():
                if (
                    isinstance(ticket, dict)
                    and ticket.get("reservation_key_sha256")
                    == reservation_key_sha256
                    and ticket.get("finalized_at") is None
                    and ticket.get("cancelled_at") is None
                ):
                    ticket["cancelled_at"] = now
                    changed = True
            return document if changed else None

        self.mutate_doc(self._doc_id(proposal_id), cancel)

    def find_by_release(self, offering_id, release_sha256, limit=2):
        if limit != 2:
            raise StudyOperationsStateError("Study operations query invalid")
        return self.query_data(
            {
                "selector": {
                    "document_type": "brainstem_study_operations",
                    "state.offeringId": offering_id,
                    "state.releaseSha256": release_sha256,
                    "state.lifecycleState": "recruiting",
                    "state.disposition": "current",
                },
                "fields": [
                    "state",
                    "participant_binding_key_id",
                    "participant_binding_key_commitment_sha256",
                ],
                "limit": limit,
            }
        )["result"]

    def privacy_snapshot(self, proposal_id, published_on):
        document = self.get_document(proposal_id)
        return next(
            (
                item
                for item in reversed(document["privacy_snapshots"])
                if item.get("publishedOn") == published_on
            ),
            None,
        )

    def publish_privacy_snapshot(
        self,
        proposal_id,
        expected_state_sha256,
        snapshot,
    ):
        result = {}

        def publish(document):
            if not self._valid_document(document, proposal_id):
                raise StudyOperationsStateError(
                    "Study operations storage unavailable"
                )
            if document["state"].get("stateSha256") != expected_state_sha256:
                raise StudyOperationsStateError("Study operations state changed")
            existing = next(
                (
                    item
                    for item in reversed(document["privacy_snapshots"])
                    if item.get("publishedOn") == snapshot["publishedOn"]
                ),
                None,
            )
            if existing is not None:
                result.update(existing)
                return None
            if len(document["privacy_snapshots"]) >= MAX_PRIVACY_SNAPSHOTS:
                raise StudyOperationsStateError(
                    "Study privacy snapshot capacity reached"
                )
            document["privacy_snapshots"].append(snapshot)
            result.update(snapshot)
            return document

        self.mutate_doc(self._doc_id(proposal_id), publish)
        return result


study_operations_dao = StudyOperationsDao()
study_operations_dao.set_config(
    config["couchdb"]["user"],
    config["couchdb"]["password"],
    config["couchdb"]["db_host"],
    config["couchdb"].get("study_operations_db", "brainstem_study_operations"),
)
