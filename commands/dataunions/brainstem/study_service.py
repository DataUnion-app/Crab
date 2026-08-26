import time

from commands.dataunions.brainstem.consent import has_brainstem_data_consent
from commands.dataunions.brainstem.study_contract import (
    STUDY_ID,
    SURVEY_VERSION,
    StudyContractError,
    create_survey_revision,
    participant_survey_projection,
    researcher_study_projection,
    supersede_survey,
    survey_contract,
)
from commands.dataunions.brainstem.study_enrollment import (
    StudyEnrollmentError,
    apply_signed_action,
    create_action_challenge,
    mark_survey_corrected,
)


class StudyServiceError(RuntimeError):
    def __init__(self, code, status_code=400):
        super().__init__(code)
        self.code = code
        self.status_code = status_code


class BrainstemStudyService:
    def __init__(self, auth, dao, clock=time.time):
        self.auth = auth
        self.dao = dao
        self.clock = clock

    def _participant(self, token, origin):
        _session_id, _session, user = self.auth.authenticate(token, origin)
        return user

    def status(self, token, origin):
        user = self._participant(token, origin)
        state = self.dao.get_state(user["_id"]) or {}
        survey = state.get("survey")
        enrollment = state.get("enrollment")
        return {
            "schema": "brainstem.study-participant-status/v1",
            "studyId": STUDY_ID,
            "availability": "candidate_review_required",
            "surveyContract": survey_contract(),
            "survey": (
                participant_survey_projection(survey) if survey else None
            ),
            "enrollment": (
                {
                    "state": enrollment["state"],
                    "enrollmentRevision": enrollment["enrollmentRevision"],
                    "startsAt": enrollment["startsAt"],
                    "endsAt": enrollment["endsAt"],
                }
                if enrollment
                else None
            ),
        }

    @staticmethod
    def _survey(body, now, previous):
        if (
            not isinstance(body, dict)
            or set(body) != {"surveyVersion", "answers"}
            or body["surveyVersion"] != SURVEY_VERSION
        ):
            raise StudyServiceError("survey_request_invalid")
        try:
            return create_survey_revision(
                body["answers"], submitted_at=now, previous=previous
            )
        except StudyContractError as error:
            raise StudyServiceError(str(error), 422) from error

    def challenge(self, token, origin, action, survey_body=None):
        if action not in {"survey", "enroll", "withdraw"}:
            raise StudyServiceError("study_action_invalid")
        user = self._participant(token, origin)
        state = self.dao.get_state(user["_id"]) or {}
        survey = state.get("survey")
        now = int(self.clock())
        if action == "survey":
            survey = self._survey(survey_body, now, state.get("survey"))
        try:
            challenge = create_action_challenge(
                user_id=user["_id"],
                address=user["public_address"],
                origin=origin,
                action=action,
                survey_revision=survey,
                current=state.get("enrollment"),
                now=now,
            )
        except (KeyError, StudyEnrollmentError) as error:
            raise StudyServiceError(str(error), 409) from error

        def update(value):
            value["challenge"] = challenge
            return value

        self.dao.mutate_state(user["_id"], update)
        return {
            "challengeId": challenge["challengeId"],
            "message": challenge["message"],
            "expiresAt": challenge["expiresAt"],
            "chainId": 11155420,
            "method": "personal_sign",
        }

    def apply(self, token, origin, challenge_id, signature, survey_body=None):
        user = self._participant(token, origin)
        now = int(self.clock())

        def update(state):
            challenge = state.get("challenge")
            if (
                not isinstance(challenge, dict)
                or challenge.get("challengeId") != challenge_id
            ):
                raise StudyServiceError("challenge_unavailable", 401)
            survey = state.get("survey")
            if challenge.get("action") == "survey":
                survey = self._survey(
                    survey_body, challenge["issuedAt"], state.get("survey")
                )
            try:
                consumed, enrollment = apply_signed_action(
                    challenge,
                    state.get("enrollment"),
                    user_id=user["_id"],
                    address=user["public_address"],
                    origin=origin,
                    action=challenge["action"],
                    signature=signature,
                    survey_revision=survey,
                    current_data_consent=has_brainstem_data_consent(user),
                    now=now,
                )
            except StudyEnrollmentError as error:
                raise StudyServiceError(str(error), 409) from error
            if challenge["action"] == "survey":
                previous = state.get("survey")
                if previous is not None and survey is not previous:
                    superseded = supersede_survey(previous)
                    state.setdefault("survey_history", []).append(superseded)
                    if state.get("enrollment"):
                        state["enrollment"] = mark_survey_corrected(
                            state["enrollment"],
                            survey["revisionSha256"],
                            changed_at=now,
                        )
                state["survey"] = survey
            else:
                state["enrollment"] = enrollment
            state["last_action"] = consumed
            state.pop("challenge", None)
            return state

        state = self.dao.mutate_state(user["_id"], update)
        if state["last_action"]["action"] == "survey":
            return participant_survey_projection(state["survey"])
        return {
            "status": state["enrollment"]["state"],
            "enrollmentRevision": state["enrollment"]["enrollmentRevision"],
        }

    def researcher_status(self):
        states = [
            {
                "enrollmentState": value.get("enrollment", {}).get("state")
            }
            for value in self.dao.researcher_projection_states()
        ]
        return researcher_study_projection(states)
