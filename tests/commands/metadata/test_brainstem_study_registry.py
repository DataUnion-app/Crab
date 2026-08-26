from copy import deepcopy

import pytest

from commands.dataunions.brainstem.study_registry import (
    APDET_DIAGNOSIS_QUESTIONNAIRE_ID,
    APDET_RETROSPECTIVE_ID,
    APDET_RETROSPECTIVE_RELEASE_SHA256,
    COMMUNITY_QUESTIONNAIRE_ID,
    DATA_UNION_ID,
    DEFAULT_STUDY_REGISTRY,
    RECORDING_FEASIBILITY_ID,
    StudyRegistry,
    StudyRegistryError,
    content_sha256,
    make_artifact,
    make_release,
    validate_artifact,
)
from commands.dataunions.studies.registry import StudyRegistry as NeutralRegistry


def amended_registry():
    release = DEFAULT_STUDY_REGISTRY.release(RECORDING_FEASIBILITY_ID, "1.0.0")
    artifacts = [
        DEFAULT_STUDY_REGISTRY.artifact(release[key])
        for key in (
            "purpose",
            "survey",
            "participantInformation",
            "protocol",
            "datasetView",
            "activationProfile",
            "taskPlan",
        )
    ]
    information_v2 = make_artifact(
        "participant_information",
        release["participantInformation"]["artifactId"],
        "2.0.0",
        {
            **artifacts[2]["content"],
            "text": "Amended generated-only participant information for version testing.",
        },
        data_union_id=DATA_UNION_ID,
    )
    release_v2 = make_release(
        RECORDING_FEASIBILITY_ID,
        "study",
        "2.0.0",
        title="Everyday resting recording study",
        summary="An amended generated-only registry fixture.",
        purpose=artifacts[0],
        survey=artifacts[1],
        participant_information=information_v2,
        protocol=artifacts[3],
        dataset_view=artifacts[4],
        activation_profile=artifacts[5],
        task_plan=artifacts[6],
        data_union_id=DATA_UNION_ID,
    )
    return StudyRegistry(
        [*artifacts, information_v2],
        [release, release_v2],
    )


def test_generated_fixtures_are_deterministic_and_keep_questionnaire_separate():
    first = DEFAULT_STUDY_REGISTRY.catalogue()
    second = DEFAULT_STUDY_REGISTRY.catalogue()

    assert first == second
    assert {item["offeringId"] for item in first} == {
        APDET_DIAGNOSIS_QUESTIONNAIRE_ID,
        RECORDING_FEASIBILITY_ID,
        COMMUNITY_QUESTIONNAIRE_ID,
    }
    study = next(item for item in first if item["offeringType"] == "study")
    questionnaire = next(
        item for item in first if item["offeringType"] == "community_questionnaire"
    )
    assert study["dataUnionId"] == DATA_UNION_ID
    assert study["datasetView"] is not None
    assert study["activationProfile"] is not None
    assert study["taskPlan"] is not None
    assert questionnaire["protocol"] is None
    assert questionnaire["datasetView"] is None
    assert questionnaire["activationProfile"] is None
    assert questionnaire["taskPlan"] is None
    assert questionnaire["surveyContract"]["questions"][1]["required"] is False
    assert questionnaire["surveyContract"]["freeTextAllowed"] is False

    diagnosis = next(
        item
        for item in first
        if item["offeringId"] == APDET_DIAGNOSIS_QUESTIONNAIRE_ID
    )
    assert diagnosis["offeringType"] == "community_questionnaire"
    assert len(diagnosis["surveyContract"]["questions"]) == 6
    assert all(
        question["required"] is False
        for question in diagnosis["surveyContract"]["questions"]
    )
    assert diagnosis["surveyContract"]["freeTextAllowed"] is False


def test_retrospective_release_is_real_cohort_but_not_participant_catalogue():
    release = DEFAULT_STUDY_REGISTRY.release(
        APDET_RETROSPECTIVE_ID,
        "1.0.0",
        APDET_RETROSPECTIVE_RELEASE_SHA256,
    )
    profile = DEFAULT_STUDY_REGISTRY.activation_profile(
        APDET_RETROSPECTIVE_ID,
        "1.0.0",
        APDET_RETROSPECTIVE_RELEASE_SHA256,
    )

    assert release["offeringType"] == "retrospective_study"
    assert release["status"] == "candidate_real_cohort"
    assert release["survey"] is None
    assert release["taskPlan"] is None
    assert profile["content"]["dataMode"] == "real_cohort"
    assert profile["content"]["algorithmNetwork"] == "none"
    assert profile["content"]["payment"] == {"currency": "none", "amountMinor": 0}
    assert APDET_RETROSPECTIVE_ID not in {
        item["offeringId"] for item in DEFAULT_STUDY_REGISTRY.catalogue()
    }


def test_release_amendment_retains_old_immutable_release_and_catalogue_uses_latest():
    registry = amended_registry()
    old = registry.release(RECORDING_FEASIBILITY_ID, "1.0.0")
    latest = registry.release(RECORDING_FEASIBILITY_ID)

    assert old["releaseVersion"] == "1.0.0"
    assert latest["releaseVersion"] == "2.0.0"
    assert old["releaseSha256"] != latest["releaseSha256"]
    assert registry.catalogue()[0]["releaseVersion"] == "2.0.0"
    with pytest.raises(StudyRegistryError, match="offering_release_unknown"):
        registry.release(
            RECORDING_FEASIBILITY_ID, "1.0.0", latest["releaseSha256"]
        )


def test_release_versions_cannot_change_data_union_or_offering_type():
    questionnaire = DEFAULT_STUDY_REGISTRY.release(
        COMMUNITY_QUESTIONNAIRE_ID, "1.0.0"
    )
    questionnaire_artifacts = [
        DEFAULT_STUDY_REGISTRY.artifact(questionnaire[key])
        for key in ("purpose", "survey", "participantInformation")
    ]
    study = DEFAULT_STUDY_REGISTRY.release(RECORDING_FEASIBILITY_ID)
    protocol = DEFAULT_STUDY_REGISTRY.artifact(study["protocol"])
    dataset = DEFAULT_STUDY_REGISTRY.artifact(study["datasetView"])
    activation = DEFAULT_STUDY_REGISTRY.artifact(study["activationProfile"])
    task_plan = DEFAULT_STUDY_REGISTRY.artifact(study["taskPlan"])
    type_drift = make_release(
        COMMUNITY_QUESTIONNAIRE_ID,
        "study",
        "2.0.0",
        title="Invalid type drift",
        summary="A release version cannot change its offering type.",
        purpose=questionnaire_artifacts[0],
        survey=questionnaire_artifacts[1],
        participant_information=questionnaire_artifacts[2],
        protocol=protocol,
        dataset_view=dataset,
        activation_profile=activation,
        task_plan=task_plan,
        data_union_id=DATA_UNION_ID,
    )
    with pytest.raises(StudyRegistryError, match="offering_identity_drift"):
        StudyRegistry(
            [*questionnaire_artifacts, protocol, dataset, activation, task_plan],
            [questionnaire, type_drift],
        )

    other_union = "other-union"
    other_artifacts = [
        make_artifact(
            artifact["kind"],
            artifact["artifactId"],
            "2.0.0",
            artifact["content"],
            data_union_id=other_union,
        )
        for artifact in questionnaire_artifacts
    ]
    union_drift = make_release(
        COMMUNITY_QUESTIONNAIRE_ID,
        "community_questionnaire",
        "2.0.0",
        title="Invalid DataUnion drift",
        summary="A release version cannot move between DataUnions.",
        purpose=other_artifacts[0],
        survey=other_artifacts[1],
        participant_information=other_artifacts[2],
        data_union_id=other_union,
    )
    with pytest.raises(StudyRegistryError, match="offering_identity_drift"):
        StudyRegistry(
            [*questionnaire_artifacts, *other_artifacts],
            [questionnaire, union_drift],
        )


def test_dataset_view_is_source_defined_and_names_only_an_adapter_capability():
    release = DEFAULT_STUDY_REGISTRY.release(RECORDING_FEASIBILITY_ID)
    artifact = DEFAULT_STUDY_REGISTRY.artifact(release["datasetView"])
    content = artifact["content"]

    assert content["sourceDefined"] is True
    assert content["fieldsCallerSelectable"] is False
    assert content["adapterCapability"] == (
        "brainstem.study-export.recording-feasibility.v1"
    )
    assert not ({"selector", "url", "roster", "fields"} & set(content))


def test_activation_profile_is_exact_generated_only_and_zero_payment():
    release = DEFAULT_STUDY_REGISTRY.release(RECORDING_FEASIBILITY_ID)
    artifact = DEFAULT_STUDY_REGISTRY.activation_profile(
        RECORDING_FEASIBILITY_ID,
        release["releaseVersion"],
        release["releaseSha256"],
    )
    profile = artifact["content"]

    assert profile["datasetCapability"] == (
        "brainstem.study-export.recording-feasibility.v1"
    )
    assert profile["dataMode"] == "generated_only"
    assert profile["algorithmNetwork"] == "none"
    assert profile["limits"]["minimumParticipants"] == 20
    assert profile["payment"] == {"currency": "none", "amountMinor": 0}
    assert profile["algorithmImageDigest"].startswith("sha256:")
    assert not ({"selector", "url", "roster", "fields", "imageTag"} & set(profile))

    for field, value, error in (
        ("algorithmImageDigest", "latest", "activation_profile_invalid"),
        ("dataMode", "production", "activation_profile_not_generated_only"),
        (
            "payment",
            {"currency": "OCEAN", "amountMinor": 1},
            "activation_payment_forbidden",
        ),
    ):
        changed = deepcopy(artifact)
        changed["content"][field] = value
        unsigned = {key: item for key, item in changed.items() if key != "sha256"}
        changed["sha256"] = content_sha256(unsigned)
        with pytest.raises(StudyRegistryError, match=error):
            validate_artifact(changed)

    added = deepcopy(artifact)
    added["content"]["selector"] = {"all": True}
    unsigned = {key: item for key, item in added.items() if key != "sha256"}
    added["sha256"] = content_sha256(unsigned)
    with pytest.raises(StudyRegistryError, match="activation_profile_invalid"):
        validate_artifact(added)


def test_prospective_study_cannot_switch_to_real_cohort_mode():
    release = DEFAULT_STUDY_REGISTRY.release(RECORDING_FEASIBILITY_ID)
    artifacts = {
        key: DEFAULT_STUDY_REGISTRY.artifact(release[key])
        for key in (
            "purpose",
            "survey",
            "participantInformation",
            "protocol",
            "datasetView",
            "activationProfile",
            "taskPlan",
        )
    }
    real_profile = make_artifact(
        "activation_profile",
        artifacts["activationProfile"]["artifactId"],
        "2.0.0",
        {**artifacts["activationProfile"]["content"], "dataMode": "real_cohort"},
        data_union_id=DATA_UNION_ID,
    )
    with pytest.raises(StudyRegistryError, match="activation_capability_mismatch"):
        make_release(
            RECORDING_FEASIBILITY_ID,
            "study",
            "2.0.0",
            title=release["title"],
            summary=release["summary"],
            purpose=artifacts["purpose"],
            survey=artifacts["survey"],
            participant_information=artifacts["participantInformation"],
            protocol=artifacts["protocol"],
            dataset_view=artifacts["datasetView"],
            activation_profile=real_profile,
            task_plan=artifacts["taskPlan"],
            data_union_id=DATA_UNION_ID,
        )


def test_task_plan_is_closed_source_owned_and_rejects_rule_language():
    release = DEFAULT_STUDY_REGISTRY.release(RECORDING_FEASIBILITY_ID)
    artifact = DEFAULT_STUDY_REGISTRY.task_plan(
        release["offeringId"], release["releaseVersion"], release["releaseSha256"]
    )
    task = artifact["content"]["tasks"][0]
    assert task["kind"] == "reviewed_recording"
    assert task["completionPolicy"] == "source_recording"
    assert task["maximumOccurrences"] == 14
    assert task["reminderPolicy"] == {
        "enabled": False,
        "earliestOffsetMinutes": 0,
        "maximumCount": 0,
    }

    for path, value, error in (
        (("kind",), "arbitrary_query", "task_plan_completion_policy_invalid"),
        (("capability",), "brainstem.arbitrary.v1", "task_plan_completion_policy_invalid"),
        (("windowEndDay",), 0, "task_window_end_invalid"),
        (("maximumOccurrences",), 15, "task_plan_window_invalid"),
        (("completionPolicy",), "caller_asserted", "task_plan_completion_policy_invalid"),
    ):
        changed = deepcopy(artifact)
        changed["content"]["tasks"][0][path[0]] = value
        changed["sha256"] = content_sha256(
            {key: item for key, item in changed.items() if key != "sha256"}
        )
        with pytest.raises(StudyRegistryError, match=error):
            validate_artifact(changed)

    injected = deepcopy(artifact)
    injected["content"]["tasks"][0]["selector"] = {"all": True}
    injected["sha256"] = content_sha256(
        {key: item for key, item in injected.items() if key != "sha256"}
    )
    with pytest.raises(StudyRegistryError, match="task_plan_task_invalid"):
        validate_artifact(injected)


def test_artifacts_reject_unknown_fields_altered_hash_and_unsafe_free_text():
    release = DEFAULT_STUDY_REGISTRY.release(COMMUNITY_QUESTIONNAIRE_ID)
    survey = DEFAULT_STUDY_REGISTRY.artifact(release["survey"])

    unknown = deepcopy(survey)
    unknown["extra"] = True
    with pytest.raises(StudyRegistryError, match="artifact_invalid"):
        validate_artifact(unknown)

    altered = deepcopy(survey)
    altered["content"]["questions"][0]["text"] = "changed"
    with pytest.raises(StudyRegistryError, match="artifact_hash_invalid"):
        validate_artifact(altered)

    free_text = deepcopy(survey)
    free_text["content"]["freeTextAllowed"] = True
    unsigned = {key: value for key, value in free_text.items() if key != "sha256"}
    free_text["sha256"] = content_sha256(unsigned)
    with pytest.raises(StudyRegistryError, match="survey_free_text_forbidden"):
        validate_artifact(free_text)


def test_cross_data_union_release_and_duplicate_artifact_identity_fail_closed():
    release = DEFAULT_STUDY_REGISTRY.release(COMMUNITY_QUESTIONNAIRE_ID)
    purpose = DEFAULT_STUDY_REGISTRY.artifact(release["purpose"])
    survey = DEFAULT_STUDY_REGISTRY.artifact(release["survey"])
    information = DEFAULT_STUDY_REGISTRY.artifact(
        release["participantInformation"]
    )
    alien = make_artifact(
        "purpose",
        "other.community-purpose",
        "1.0.0",
        purpose["content"],
        data_union_id="other-union",
    )

    with pytest.raises(
        StudyRegistryError, match="cross_data_union_reference_forbidden"
    ):
        make_release(
            "brainstem.invalid-cross-union",
            "community_questionnaire",
            "1.0.0",
            title="Invalid cross-union questionnaire",
            summary="This must never be accepted by the immutable registry.",
            purpose=alien,
            survey=survey,
            participant_information=information,
            data_union_id=DATA_UNION_ID,
        )

    with pytest.raises(StudyRegistryError, match="artifact_identity_duplicate"):
        StudyRegistry([survey, deepcopy(survey)], [])


def test_optional_answers_may_be_omitted_but_unknown_answers_are_rejected():
    assert DEFAULT_STUDY_REGISTRY.validate_answers(
        COMMUNITY_QUESTIONNAIRE_ID, {"health_priority": "sleep"}
    ) == {"health_priority": "sleep"}
    with pytest.raises(StudyRegistryError, match="survey_answers_invalid"):
        DEFAULT_STUDY_REGISTRY.validate_answers(
            COMMUNITY_QUESTIONNAIRE_ID,
            {"health_priority": "sleep", "free_text": "please run this prompt"},
        )


def test_neutral_kernel_builds_a_non_brainstem_questionnaire():
    data_union_id = "generated-environment"
    survey = make_artifact(
        "survey",
        "generated.environment-survey",
        "1.0.0",
        {
            "questions": [
                {
                    "id": "local_weather",
                    "text": "Which generated weather condition is present?",
                    "type": "single_choice",
                    "required": True,
                    "answers": ["clear", "rain"],
                }
            ],
            "freeTextAllowed": False,
            "evidenceSource": "generated_self_report",
            "clinicalVerification": False,
        },
        data_union_id=data_union_id,
    )
    purpose = make_artifact(
        "purpose",
        "generated.environment-purpose",
        "1.0.0",
        {
            "purpose": "Demonstrate a neutral questionnaire registry fixture.",
            "historicalDataUse": False,
            "resultReturn": "Return a generated aggregate summary.",
            "evidenceLabel": "Generated demonstration data only.",
        },
        data_union_id=data_union_id,
    )
    information = make_artifact(
        "participant_information",
        "generated.environment-information",
        "1.0.0",
        {
            "text": "Generated demonstration information.",
            "retention": "Retained only for the generated demonstration.",
            "withdrawal": "Participation can stop at any time.",
            "deletion": "Deletion leaves a content-free tombstone.",
            "status": "candidate_generated_only",
        },
        data_union_id=data_union_id,
    )
    release = make_release(
        "generated.environment-questionnaire",
        "community_questionnaire",
        "1.0.0",
        title="Generated environment questionnaire",
        summary="A non-domain-specific generated registry proof.",
        purpose=purpose,
        survey=survey,
        participant_information=information,
        data_union_id=data_union_id,
    )
    registry = NeutralRegistry([survey, purpose, information], [release])

    public = registry.catalogue()[0]
    assert public["schema"] == "dataunion.study-offering-release/v1"
    assert public["dataUnionId"] == data_union_id
    assert registry.validate_answers(
        public["offeringId"], {"local_weather": "clear"}
    ) == {"local_weather": "clear"}


def test_registry_enforces_question_offering_and_answer_identifier_bounds():
    release = DEFAULT_STUDY_REGISTRY.release(COMMUNITY_QUESTIONNAIRE_ID)
    survey = DEFAULT_STUDY_REGISTRY.artifact(release["survey"])
    too_many_questions = deepcopy(survey)
    too_many_questions["content"]["questions"] = [
        {
            "id": "question.{}".format(index),
            "text": "Generated bounded question {}?".format(index),
            "type": "single_choice",
            "required": True,
            "answers": ["no", "yes"],
        }
        for index in range(33)
    ]
    unsigned = {
        key: value for key, value in too_many_questions.items() if key != "sha256"
    }
    too_many_questions["sha256"] = content_sha256(unsigned)
    with pytest.raises(StudyRegistryError, match="survey_artifact_invalid"):
        validate_artifact(too_many_questions)

    for invalid in ("Uppercase", "a" * 65):
        invalid_answer = deepcopy(survey)
        invalid_answer["content"]["questions"][0]["answers"] = ["valid", invalid]
        unsigned = {
            key: value for key, value in invalid_answer.items() if key != "sha256"
        }
        invalid_answer["sha256"] = content_sha256(unsigned)
        with pytest.raises(StudyRegistryError, match="survey_question_invalid"):
            validate_artifact(invalid_answer)

    artifacts = [
        DEFAULT_STUDY_REGISTRY.artifact(release[key])
        for key in ("purpose", "survey", "participantInformation")
    ]
    releases = [
        make_release(
            "brainstem.generated-questionnaire.{}".format(index),
            "community_questionnaire",
            "1.0.0",
            title="Generated questionnaire {}".format(index),
            summary="Generated offering used only to prove the registry bound.",
            purpose=artifacts[0],
            survey=artifacts[1],
            participant_information=artifacts[2],
            data_union_id=DATA_UNION_ID,
        )
        for index in range(33)
    ]
    with pytest.raises(StudyRegistryError, match="offering_limit_exceeded"):
        StudyRegistry(artifacts, releases)
