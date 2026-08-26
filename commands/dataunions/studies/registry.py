"""Immutable, DataUnion-neutral study and questionnaire registry.

The registry is deliberately data-only.  It has no query language, activation
state, or exporter callback: releases may describe a source-defined dataset
view, but only separately reviewed production code can materialize one.
"""

from copy import deepcopy
import hashlib
import json
import re


class StudyRegistryError(ValueError):
    pass


IDENTIFIER = re.compile(r"^[a-z0-9][a-z0-9._-]{2,127}$")
ANSWER_IDENTIFIER = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
VERSION = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
OFFERING_TYPES = {"study", "retrospective_study", "community_questionnaire"}
QUESTION_TYPES = {"single_choice", "boolean"}
ARTIFACT_KINDS = {
    "activation_profile",
    "protocol",
    "survey",
    "participant_information",
    "purpose",
    "dataset_view",
    "task_plan",
}
MAX_OFFERINGS = 32
MAX_QUESTIONS = 32
MAX_TASKS = 16
IMAGE_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
# Protocol survey and acknowledgement tasks remain unavailable until their
# immutable artifact references are part of this closed task schema.
TASK_CAPABILITIES = {
    "brainstem.recording.resting-rr.reviewed.v1": (
        "reviewed_recording",
        "source_recording",
    ),
}


def canonical_json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def content_sha256(value):
    return hashlib.sha256(canonical_json(value)).hexdigest()


def _text(value, name, minimum=1, maximum=4000):
    if not isinstance(value, str):
        raise StudyRegistryError("{}_invalid".format(name))
    value = value.strip()
    if not minimum <= len(value) <= maximum:
        raise StudyRegistryError("{}_invalid".format(name))
    if any(ord(character) < 32 and character not in "\n\t" for character in value):
        raise StudyRegistryError("{}_invalid".format(name))
    return value


def _identity(value, name):
    value = _text(value, name, maximum=128)
    if not IDENTIFIER.fullmatch(value):
        raise StudyRegistryError("{}_invalid".format(name))
    return value


def make_artifact(kind, artifact_id, version, content, *, data_union_id):
    if kind not in ARTIFACT_KINDS:
        raise StudyRegistryError("artifact_kind_invalid")
    _identity(artifact_id, "artifact_id")
    if not isinstance(version, str) or not VERSION.fullmatch(version):
        raise StudyRegistryError("artifact_version_invalid")
    if not isinstance(content, dict):
        raise StudyRegistryError("artifact_content_invalid")
    artifact = {
        "schema": "dataunion.study-artifact/v1",
        "dataUnionId": _identity(data_union_id, "data_union_id"),
        "kind": kind,
        "artifactId": artifact_id,
        "version": version,
        "content": deepcopy(content),
    }
    artifact["sha256"] = content_sha256(artifact)
    validate_artifact(artifact)
    return artifact


def validate_artifact(value):
    expected = {
        "schema",
        "dataUnionId",
        "kind",
        "artifactId",
        "version",
        "content",
        "sha256",
    }
    if not isinstance(value, dict) or set(value) != expected:
        raise StudyRegistryError("artifact_invalid")
    if value.get("schema") != "dataunion.study-artifact/v1":
        raise StudyRegistryError("artifact_invalid")
    if value.get("kind") not in ARTIFACT_KINDS:
        raise StudyRegistryError("artifact_invalid")
    _identity(value.get("artifactId"), "artifact_id")
    _identity(value.get("dataUnionId"), "data_union_id")
    if not isinstance(value.get("version"), str) or not VERSION.fullmatch(
        value["version"]
    ):
        raise StudyRegistryError("artifact_invalid")
    if not isinstance(value.get("content"), dict):
        raise StudyRegistryError("artifact_invalid")
    supplied = value.get("sha256")
    unsigned = {key: deepcopy(item) for key, item in value.items() if key != "sha256"}
    if not isinstance(supplied, str) or not SHA256.fullmatch(supplied):
        raise StudyRegistryError("artifact_invalid")
    if supplied != content_sha256(unsigned):
        raise StudyRegistryError("artifact_hash_invalid")
    validator = {
        "activation_profile": _validate_activation_profile_content,
        "task_plan": _validate_task_plan_content,
        "survey": _validate_survey_content,
        "purpose": _validate_purpose_content,
        "participant_information": _validate_information_content,
        "protocol": _validate_protocol_content,
        "dataset_view": _validate_dataset_view_content,
    }[value["kind"]]
    validator(value["content"])
    return value


def _strict_int(value, name, minimum, maximum):
    if type(value) is not int or not minimum <= value <= maximum:
        raise StudyRegistryError("{}_invalid".format(name))
    return value


def _validate_activation_profile_content(value):
    expected = {
        "profileId",
        "datasetCapability",
        "algorithmId",
        "algorithmVersion",
        "algorithmSourceSha256",
        "algorithmImageDigest",
        "approvedManifestSha256",
        "referenceSha256",
        "resultContractId",
        "resultContractSha256",
        "operationalPolicyId",
        "operationalPolicySha256",
        "environment",
        "dataMode",
        "algorithmNetwork",
        "limits",
        "permitTtlSeconds",
        "payment",
    }
    if not isinstance(value, dict) or set(value) != expected:
        raise StudyRegistryError("activation_profile_invalid")
    for field in (
        "profileId",
        "datasetCapability",
        "algorithmId",
        "resultContractId",
        "operationalPolicyId",
        "environment",
    ):
        _identity(value[field], field)
    if not isinstance(value["algorithmVersion"], str) or not VERSION.fullmatch(
        value["algorithmVersion"]
    ):
        raise StudyRegistryError("activation_profile_invalid")
    for field in (
        "algorithmSourceSha256",
        "approvedManifestSha256",
        "referenceSha256",
        "resultContractSha256",
        "operationalPolicySha256",
    ):
        if not isinstance(value[field], str) or not SHA256.fullmatch(value[field]):
            raise StudyRegistryError("activation_profile_invalid")
    if not isinstance(value["algorithmImageDigest"], str) or not IMAGE_DIGEST.fullmatch(
        value["algorithmImageDigest"]
    ):
        raise StudyRegistryError("activation_profile_invalid")
    if value["dataMode"] not in {"generated_only", "real_cohort"} or value[
        "algorithmNetwork"
    ] != "none":
        raise StudyRegistryError("activation_profile_not_generated_only")
    limits = value["limits"]
    expected_limits = {
        "minimumParticipants",
        "maximumParticipants",
        "maximumRecordingsPerParticipant",
        "maximumTotalRecordings",
        "maximumInputBytes",
        "maximumResultBytes",
        "maximumJobDurationSeconds",
    }
    if not isinstance(limits, dict) or set(limits) != expected_limits:
        raise StudyRegistryError("activation_limits_invalid")
    minimum = _strict_int(
        limits["minimumParticipants"], "minimum_participants", 20, 100000
    )
    maximum = _strict_int(
        limits["maximumParticipants"], "maximum_participants", minimum, 100000
    )
    recordings = _strict_int(
        limits["maximumRecordingsPerParticipant"],
        "maximum_recordings_per_participant",
        1,
        365,
    )
    _strict_int(
        limits["maximumTotalRecordings"],
        "maximum_total_recordings",
        maximum,
        maximum * recordings,
    )
    _strict_int(
        limits["maximumInputBytes"],
        "maximum_input_bytes",
        1,
        64 * 1024 * 1024,
    )
    _strict_int(limits["maximumResultBytes"], "maximum_result_bytes", 1, 1024 * 1024)
    _strict_int(
        limits["maximumJobDurationSeconds"],
        "maximum_job_duration_seconds",
        1,
        3600,
    )
    _strict_int(value["permitTtlSeconds"], "permit_ttl_seconds", 60, 7 * 86400)
    if value["payment"] != {"currency": "none", "amountMinor": 0}:
        raise StudyRegistryError("activation_payment_forbidden")


def _validate_task_plan_content(value):
    if not isinstance(value, dict) or set(value) != {"planId", "timezone", "tasks"}:
        raise StudyRegistryError("task_plan_invalid")
    _identity(value["planId"], "plan_id")
    if value["timezone"] != "UTC":
        raise StudyRegistryError("task_plan_timezone_invalid")
    tasks = value["tasks"]
    if not isinstance(tasks, list) or not 1 <= len(tasks) <= MAX_TASKS:
        raise StudyRegistryError("task_plan_invalid")
    task_ids = set()
    total_occurrences = 0
    for task in tasks:
        if not isinstance(task, dict) or set(task) != {
            "taskId",
            "kind",
            "capability",
            "windowStartDay",
            "windowEndDay",
            "cadenceDays",
            "maximumOccurrences",
            "completionPolicy",
            "burdenMinutes",
            "reminderPolicy",
        }:
            raise StudyRegistryError("task_plan_task_invalid")
        task_id = _identity(task["taskId"], "task_id")
        if task_id in task_ids:
            raise StudyRegistryError("task_plan_task_duplicate")
        task_ids.add(task_id)
        capability = _identity(task["capability"], "task_capability")
        if TASK_CAPABILITIES.get(capability) != (
            task["kind"],
            task["completionPolicy"],
        ):
            raise StudyRegistryError("task_plan_completion_policy_invalid")
        start = _strict_int(task["windowStartDay"], "task_window_start", 0, 365)
        end = _strict_int(task["windowEndDay"], "task_window_end", 1, 366)
        cadence = _strict_int(task["cadenceDays"], "task_cadence", 1, 30)
        occurrences = _strict_int(
            task["maximumOccurrences"], "task_occurrences", 1, 365
        )
        if end <= start or occurrences > ((end - start - 1) // cadence) + 1:
            raise StudyRegistryError("task_plan_window_invalid")
        _strict_int(task["burdenMinutes"], "task_burden", 0, 240)
        reminder = task["reminderPolicy"]
        if not isinstance(reminder, dict) or set(reminder) != {
            "enabled",
            "earliestOffsetMinutes",
            "maximumCount",
        }:
            raise StudyRegistryError("task_plan_reminder_invalid")
        if not isinstance(reminder["enabled"], bool):
            raise StudyRegistryError("task_plan_reminder_invalid")
        earliest = _strict_int(
            reminder["earliestOffsetMinutes"],
            "task_reminder_offset",
            0,
            7 * 24 * 60,
        )
        maximum = _strict_int(
            reminder["maximumCount"], "task_reminder_count", 0, 7
        )
        if (not reminder["enabled"] and (earliest != 0 or maximum != 0)) or (
            reminder["enabled"] and maximum == 0
        ):
            raise StudyRegistryError("task_plan_reminder_invalid")
        total_occurrences += occurrences
    if total_occurrences > 365:
        raise StudyRegistryError("task_plan_occurrences_exceeded")


def _validate_survey_content(value):
    if not isinstance(value, dict) or set(value) != {
        "questions",
        "freeTextAllowed",
        "evidenceSource",
        "clinicalVerification",
    }:
        raise StudyRegistryError("survey_artifact_invalid")
    if value["freeTextAllowed"] is not False:
        raise StudyRegistryError("survey_free_text_forbidden")
    _text(value["evidenceSource"], "evidence_source", maximum=128)
    if not isinstance(value["clinicalVerification"], bool):
        raise StudyRegistryError("survey_artifact_invalid")
    questions = value["questions"]
    if not isinstance(questions, list) or not 1 <= len(questions) <= MAX_QUESTIONS:
        raise StudyRegistryError("survey_artifact_invalid")
    seen = set()
    for question in questions:
        if not isinstance(question, dict) or set(question) != {
            "id",
            "text",
            "type",
            "required",
            "answers",
        }:
            raise StudyRegistryError("survey_question_invalid")
        question_id = _identity(question["id"], "question_id")
        if question_id in seen:
            raise StudyRegistryError("survey_question_duplicate")
        seen.add(question_id)
        _text(question["text"], "question_text", maximum=500)
        if question["type"] not in QUESTION_TYPES or not isinstance(
            question["required"], bool
        ):
            raise StudyRegistryError("survey_question_invalid")
        answers = question["answers"]
        if question["type"] == "boolean":
            if answers != [True, False]:
                raise StudyRegistryError("survey_question_invalid")
        elif (
            not isinstance(answers, list)
            or not 2 <= len(answers) <= 12
            or len(set(answers)) != len(answers)
            or any(
                not isinstance(answer, str)
                or not ANSWER_IDENTIFIER.fullmatch(answer)
                for answer in answers
            )
        ):
            raise StudyRegistryError("survey_question_invalid")


def _validate_purpose_content(value):
    required = {"purpose", "historicalDataUse", "resultReturn", "evidenceLabel"}
    if not isinstance(value, dict) or set(value) != required:
        raise StudyRegistryError("purpose_artifact_invalid")
    _text(value["purpose"], "purpose", maximum=2000)
    _text(value["resultReturn"], "result_return", maximum=1000)
    _text(value["evidenceLabel"], "evidence_label", maximum=256)
    if not isinstance(value["historicalDataUse"], bool):
        raise StudyRegistryError("purpose_artifact_invalid")


def _validate_information_content(value):
    required = {"text", "retention", "withdrawal", "deletion", "status"}
    if not isinstance(value, dict) or set(value) != required:
        raise StudyRegistryError("information_artifact_invalid")
    for field in required:
        _text(value[field], field, maximum=8000)


def _validate_protocol_content(value):
    required = {"population", "burden", "schedule", "endpoints", "analysisPlan"}
    if not isinstance(value, dict) or set(value) != required:
        raise StudyRegistryError("protocol_artifact_invalid")
    for field in required:
        _text(value[field], field, maximum=4000)


def _validate_dataset_view_content(value):
    required = {
        "schema",
        "policy",
        "adapterCapability",
        "sourceDefined",
        "fieldsCallerSelectable",
    }
    if not isinstance(value, dict) or set(value) != required:
        raise StudyRegistryError("dataset_view_artifact_invalid")
    _identity(value["schema"], "dataset_schema")
    _identity(value["policy"], "dataset_policy")
    _identity(value["adapterCapability"], "adapter_capability")
    if value["sourceDefined"] is not True or value["fieldsCallerSelectable"] is not False:
        raise StudyRegistryError("dataset_view_not_source_defined")


def artifact_ref(artifact):
    validate_artifact(artifact)
    return {
        "dataUnionId": artifact["dataUnionId"],
        "artifactId": artifact["artifactId"],
        "version": artifact["version"],
        "sha256": artifact["sha256"],
    }


def make_release(
    offering_id,
    offering_type,
    version,
    *,
    title,
    summary,
    purpose,
    survey=None,
    participant_information,
    protocol=None,
    dataset_view=None,
    activation_profile=None,
    task_plan=None,
    data_union_id,
):
    _identity(offering_id, "offering_id")
    if offering_type not in OFFERING_TYPES:
        raise StudyRegistryError("offering_type_invalid")
    if not isinstance(version, str) or not VERSION.fullmatch(version):
        raise StudyRegistryError("release_version_invalid")
    if offering_type == "study" and (
        protocol is None
        or dataset_view is None
        or activation_profile is None
        or task_plan is None
        or survey is None
    ):
        raise StudyRegistryError("study_artifacts_required")
    if offering_type == "retrospective_study" and (
        protocol is None
        or dataset_view is None
        or activation_profile is None
        or survey is not None
        or task_plan is not None
    ):
        raise StudyRegistryError("retrospective_study_artifacts_invalid")
    if offering_type == "community_questionnaire" and (
        survey is None
        or protocol is not None
        or dataset_view is not None
        or activation_profile is not None
        or task_plan is not None
    ):
        raise StudyRegistryError("questionnaire_dataset_forbidden")
    artifacts = [purpose, participant_information]
    if survey is not None:
        artifacts.append(survey)
    if protocol is not None:
        artifacts.append(protocol)
    if dataset_view is not None:
        artifacts.append(dataset_view)
    if activation_profile is not None:
        artifacts.append(activation_profile)
    if task_plan is not None:
        artifacts.append(task_plan)
    for artifact in artifacts:
        validate_artifact(artifact)
        if artifact["dataUnionId"] != data_union_id:
            raise StudyRegistryError("cross_data_union_reference_forbidden")
    release = {
        "schema": "dataunion.study-offering-release/v1",
        "dataUnionId": _identity(data_union_id, "data_union_id"),
        "offeringId": offering_id,
        "offeringType": offering_type,
        "releaseVersion": version,
        "status": (
            "candidate_real_cohort"
            if offering_type == "retrospective_study"
            else "candidate_generated_only"
        ),
        "title": _text(title, "title", maximum=160),
        "summary": _text(summary, "summary", maximum=1000),
        "purpose": artifact_ref(purpose),
        "survey": artifact_ref(survey) if survey else None,
        "participantInformation": artifact_ref(participant_information),
        "protocol": artifact_ref(protocol) if protocol else None,
        "datasetView": artifact_ref(dataset_view) if dataset_view else None,
        "activationProfile": (
            artifact_ref(activation_profile) if activation_profile else None
        ),
        "taskPlan": artifact_ref(task_plan) if task_plan else None,
    }
    release["releaseSha256"] = content_sha256(release)
    validate_release(release, artifacts={item["sha256"]: item for item in artifacts})
    return release


def validate_release(value, *, artifacts):
    expected = {
        "schema",
        "dataUnionId",
        "offeringId",
        "offeringType",
        "releaseVersion",
        "status",
        "title",
        "summary",
        "purpose",
        "survey",
        "participantInformation",
        "protocol",
        "datasetView",
        "activationProfile",
        "taskPlan",
        "releaseSha256",
    }
    if not isinstance(value, dict) or set(value) != expected:
        raise StudyRegistryError("release_invalid")
    if value["schema"] != "dataunion.study-offering-release/v1":
        raise StudyRegistryError("release_invalid")
    _identity(value["offeringId"], "offering_id")
    _identity(value["dataUnionId"], "data_union_id")
    if value["offeringType"] not in OFFERING_TYPES:
        raise StudyRegistryError("release_invalid")
    expected_status = (
        "candidate_real_cohort"
        if value["offeringType"] == "retrospective_study"
        else "candidate_generated_only"
    )
    if value["status"] != expected_status:
        raise StudyRegistryError("release_activation_forbidden")
    if not VERSION.fullmatch(value["releaseVersion"]):
        raise StudyRegistryError("release_invalid")
    _text(value["title"], "title", maximum=160)
    _text(value["summary"], "summary", maximum=1000)
    expected_kinds = {
        "purpose": "purpose",
        "survey": "survey",
        "participantInformation": "participant_information",
        "protocol": "protocol",
        "datasetView": "dataset_view",
        "activationProfile": "activation_profile",
        "taskPlan": "task_plan",
    }
    for field, kind in expected_kinds.items():
        reference = value[field]
        if reference is None:
            if field == "survey" and value["offeringType"] == "retrospective_study":
                continue
            if field not in {
                "protocol",
                "datasetView",
                "activationProfile",
                "taskPlan",
            }:
                raise StudyRegistryError("release_artifact_missing")
            continue
        if not isinstance(reference, dict) or set(reference) != {
            "dataUnionId",
            "artifactId",
            "version",
            "sha256",
        }:
            raise StudyRegistryError("release_artifact_invalid")
        artifact = artifacts.get(reference.get("sha256"))
        if (
            artifact is None
            or artifact_ref(artifact) != reference
            or artifact["kind"] != kind
            or artifact["dataUnionId"] != value["dataUnionId"]
        ):
            raise StudyRegistryError("release_artifact_invalid")
    if value["offeringType"] == "study":
        if (
            value["protocol"] is None
            or value["datasetView"] is None
            or value["activationProfile"] is None
            or value["taskPlan"] is None
        ):
            raise StudyRegistryError("study_artifacts_required")
        dataset = artifacts[value["datasetView"]["sha256"]]["content"]
        activation = artifacts[value["activationProfile"]["sha256"]]["content"]
        if (
            activation["datasetCapability"] != dataset["adapterCapability"]
            or activation["dataMode"] != "generated_only"
        ):
            raise StudyRegistryError("activation_capability_mismatch")
    elif value["offeringType"] == "retrospective_study":
        if (
            value["survey"] is not None
            or value["taskPlan"] is not None
            or value["protocol"] is None
            or value["datasetView"] is None
            or value["activationProfile"] is None
        ):
            raise StudyRegistryError("retrospective_study_artifacts_invalid")
        dataset = artifacts[value["datasetView"]["sha256"]]["content"]
        activation = artifacts[value["activationProfile"]["sha256"]]["content"]
        if (
            activation["datasetCapability"] != dataset["adapterCapability"]
            or activation["dataMode"] != "real_cohort"
        ):
            raise StudyRegistryError("activation_capability_mismatch")
    elif (
        value["protocol"] is not None
        or value["datasetView"] is not None
        or value["activationProfile"] is not None
        or value["taskPlan"] is not None
    ):
        raise StudyRegistryError("questionnaire_dataset_forbidden")
    unsigned = {key: deepcopy(item) for key, item in value.items() if key != "releaseSha256"}
    if value["releaseSha256"] != content_sha256(unsigned):
        raise StudyRegistryError("release_hash_invalid")
    return value


class StudyRegistry:
    def __init__(self, artifacts, releases, answer_validators=None):
        self._answer_validators = dict(answer_validators or {})
        self._artifacts = {}
        for artifact in artifacts:
            validate_artifact(artifact)
            key = (artifact["artifactId"], artifact["version"])
            if key in self._artifacts:
                raise StudyRegistryError("artifact_identity_duplicate")
            self._artifacts[key] = deepcopy(artifact)
        by_hash = {value["sha256"]: value for value in self._artifacts.values()}
        self._releases = {}
        offering_ids = set()
        offering_identities = {}
        for release in releases:
            validate_release(release, artifacts=by_hash)
            identity = (release["dataUnionId"], release["offeringType"])
            previous_identity = offering_identities.get(release["offeringId"])
            if previous_identity is not None and previous_identity != identity:
                raise StudyRegistryError("offering_identity_drift")
            offering_identities[release["offeringId"]] = identity
            key = (release["offeringId"], release["releaseVersion"])
            if key in self._releases:
                raise StudyRegistryError("offering_identity_duplicate")
            self._releases[key] = deepcopy(release)
            offering_ids.add(release["offeringId"])
        if len(offering_ids) > MAX_OFFERINGS:
            raise StudyRegistryError("offering_limit_exceeded")

    def catalogue(self):
        offering_ids = sorted(
            {
                key[0]
                for key, release in self._releases.items()
                if release["offeringType"] != "retrospective_study"
            }
        )
        return [self.public(offering_id) for offering_id in offering_ids]

    def release(self, offering_id, release_version=None, release_sha256=None):
        if not isinstance(offering_id, str):
            raise StudyRegistryError("offering_unknown")
        if release_version is None:
            versions = [
                key[1] for key in self._releases if key[0] == offering_id
            ]
            if not versions:
                raise StudyRegistryError("offering_unknown")
            release_version = max(
                versions, key=lambda value: tuple(int(part) for part in value.split("."))
            )
        try:
            release = deepcopy(self._releases[(offering_id, release_version)])
        except (KeyError, TypeError):
            raise StudyRegistryError("offering_release_unknown")
        if release_sha256 is not None and release["releaseSha256"] != release_sha256:
            raise StudyRegistryError("offering_release_unknown")
        return release

    def artifact(self, reference):
        if not isinstance(reference, dict):
            raise StudyRegistryError("artifact_reference_invalid")
        key = (reference.get("artifactId"), reference.get("version"))
        artifact = self._artifacts.get(key)
        if artifact is None or artifact_ref(artifact) != reference:
            raise StudyRegistryError("artifact_reference_invalid")
        return deepcopy(artifact)

    def activation_profile(
        self,
        offering_id,
        release_version=None,
        release_sha256=None,
    ):
        release = self.release(offering_id, release_version, release_sha256)
        if release["offeringType"] not in {"study", "retrospective_study"} or release[
            "activationProfile"
        ] is None:
            raise StudyRegistryError("study_activation_profile_unavailable")
        return self.artifact(release["activationProfile"])

    def task_plan(
        self,
        offering_id,
        release_version=None,
        release_sha256=None,
    ):
        release = self.release(offering_id, release_version, release_sha256)
        if release["offeringType"] != "study" or release["taskPlan"] is None:
            raise StudyRegistryError("study_task_plan_unavailable")
        return self.artifact(release["taskPlan"])

    def public(self, offering_id, release_version=None):
        release = self.release(offering_id, release_version)
        purpose = self.artifact(release["purpose"])["content"]
        survey = (
            self.artifact(release["survey"])["content"]
            if release["survey"]
            else None
        )
        information = self.artifact(release["participantInformation"])["content"]
        return {
            **release,
            "purposeDetails": purpose,
            "surveyContract": survey,
            "participantInformationDetails": information,
            "protocolDetails": (
                self.artifact(release["protocol"])["content"]
                if release["protocol"]
                else None
            ),
            "taskPlanDetails": (
                self.artifact(release["taskPlan"])["content"]
                if release["taskPlan"]
                else None
            ),
        }

    def validate_answers(
        self,
        offering_id,
        answers,
        release_version=None,
        release_sha256=None,
    ):
        release = self.release(offering_id, release_version, release_sha256)
        if release["survey"] is None:
            raise StudyRegistryError("survey_answers_unavailable")
        survey = self.artifact(release["survey"])["content"]
        if not isinstance(answers, dict):
            raise StudyRegistryError("survey_answers_invalid")
        questions = {question["id"]: question for question in survey["questions"]}
        required = {key for key, question in questions.items() if question["required"]}
        if not required <= set(answers) or not set(answers) <= set(questions):
            raise StudyRegistryError("survey_answers_invalid")
        normalized = {}
        for key in sorted(answers):
            value = answers[key]
            question = questions[key]
            if value not in question["answers"]:
                raise StudyRegistryError("survey_answers_invalid")
            normalized[key] = value
        validator = self._answer_validators.get(offering_id)
        if validator is not None:
            validator(deepcopy(normalized))
        return normalized
