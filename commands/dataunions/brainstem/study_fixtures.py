"""Generated-only Brainstem fixtures for the neutral studies registry."""

from commands.dataunions.studies.registry import (
    StudyRegistry,
    StudyRegistryError,
    content_sha256,
    make_artifact,
    make_release,
)


DATA_UNION_ID = "brainstem"
APDET_RETROSPECTIVE_ID = "brainstem.apdet-retrospective-study"
APDET_DIAGNOSIS_QUESTIONNAIRE_ID = (
    "brainstem.apdet-retrospective-diagnosis-context"
)
RECORDING_FEASIBILITY_ID = (
    "brainstem.real-world-recording-feasibility-repeatability"
)
COMMUNITY_QUESTIONNAIRE_ID = "brainstem.community-health-questionnaire"
LEGACY_RECORDING_FEASIBILITY_SLUG = "recording-feasibility"


def _artifact(kind, artifact_id, content):
    return make_artifact(
        kind,
        artifact_id,
        "1.0.0",
        content,
        data_union_id=DATA_UNION_ID,
    )


def _question(question_id, text, answers, required=True):
    return {
        "id": question_id,
        "text": text,
        "type": "single_choice",
        "required": required,
        "answers": list(answers),
    }


_STUDY_SURVEY = _artifact(
    "survey",
    "brainstem.recording-feasibility-survey",
    {
        "questions": [
            _question(
                "adult_status",
                "Are you 18 years old or older?",
                ("yes", "no", "prefer_not_to_say"),
            ),
            _question(
                "chronic_condition_status",
                "Do you live with one or more long-term health conditions?",
                ("no", "prefer_not_to_say", "unsure", "yes"),
            ),
            _question(
                "clinician_confirmation_status",
                "Has a qualified clinician told you that you have a long-term health condition?",
                ("no", "prefer_not_to_say", "unsure", "yes"),
            ),
        ],
        "freeTextAllowed": False,
        "evidenceSource": "participant_self_report",
        "clinicalVerification": False,
    },
)
_STUDY_PURPOSE = _artifact(
    "purpose",
    "brainstem.recording-feasibility-purpose",
    {
        "purpose": "Test whether ordinary resting recordings can support a repeatable feasibility analysis.",
        "historicalDataUse": False,
        "resultReturn": "Participants may later receive a reviewed plain-language study summary.",
        "evidenceLabel": "Self-reported answers are research context, not a diagnosis or verified ground truth.",
    },
)
_STUDY_INFORMATION = _artifact(
    "participant_information",
    "brainstem.recording-feasibility-information",
    {
        "text": "Candidate wording for generated testing only. Joining would allow eligible Brainstem resting recordings from fourteen full UTC study days to contribute to one feasibility study.",
        "retention": "Versioned study evidence is retained under the candidate generated-only policy.",
        "withdrawal": "Leaving stops selection of new recordings and retains already collected study evidence under the disclosed policy.",
        "deletion": "Deleting a questionnaire response removes answer content, leaves a content-free tombstone, and excludes future use.",
        "status": "candidate_generated_only",
    },
)
_STUDY_PROTOCOL = _artifact(
    "protocol",
    "brainstem.recording-feasibility-protocol",
    {
        "population": "Adults who voluntarily answer the candidate questionnaire and retain Brainstem data-sharing consent.",
        "burden": "One ordinary five-minute resting recording on each of fourteen study days.",
        "schedule": "Prospective fourteen-day window beginning at the next UTC day boundary.",
        "endpoints": "Feasibility and repeatability of eligible resting R-R recordings.",
        "analysisPlan": "Use only the source-defined generated feasibility dataset view and its separately approved algorithm.",
    },
)
_STUDY_DATASET = _artifact(
    "dataset_view",
    "brainstem.recording-feasibility-dataset",
    {
        "schema": "brainstem.recording-feasibility-rr.v1",
        "policy": "brainstem.recording-feasibility-rr.14d-v1",
        "adapterCapability": "brainstem.study-export.recording-feasibility.v1",
        "sourceDefined": True,
        "fieldsCallerSelectable": False,
    },
)
_STUDY_ACTIVATION_PROFILE = _artifact(
    "activation_profile",
    "brainstem.recording-feasibility-generated-activation",
    {
        "profileId": "brainstem.recording-feasibility.generated-local",
        "datasetCapability": "brainstem.study-export.recording-feasibility.v1",
        "algorithmId": "brainstem.recording-feasibility-rr-summary",
        "algorithmVersion": "0.1.0",
        "algorithmSourceSha256": content_sha256(
            {"generatedFixture": "recording-feasibility-algorithm-source/v1"}
        ),
        "algorithmImageDigest": "sha256:"
        + content_sha256(
            {"generatedFixture": "recording-feasibility-algorithm-image/v1"}
        ),
        "approvedManifestSha256": content_sha256(
            {"generatedFixture": "recording-feasibility-approved-manifest/v1"}
        ),
        "referenceSha256": content_sha256(
            {"generatedFixture": "recording-feasibility-reference/v1"}
        ),
        "resultContractId": "brainstem.recording-feasibility-result.v1",
        "resultContractSha256": content_sha256(
            {"generatedFixture": "recording-feasibility-result-contract/v1"}
        ),
        "operationalPolicyId": "brainstem.study-operations.generated-local.v1",
        "operationalPolicySha256": content_sha256(
            {"generatedFixture": "study-operations-policy/v1"}
        ),
        "environment": "generated-local",
        "dataMode": "generated_only",
        "algorithmNetwork": "none",
        "limits": {
            "minimumParticipants": 20,
            "maximumParticipants": 100,
            "maximumRecordingsPerParticipant": 14,
            "maximumTotalRecordings": 1400,
            "maximumInputBytes": 16777216,
            "maximumResultBytes": 262144,
            "maximumJobDurationSeconds": 60,
        },
        "permitTtlSeconds": 86400,
        "payment": {"currency": "none", "amountMinor": 0},
    },
)
_STUDY_TASK_PLAN = _artifact(
    "task_plan",
    "brainstem.recording-feasibility-task-plan",
    {
        "planId": "brainstem.recording-feasibility.14-day",
        "timezone": "UTC",
        "tasks": [
            {
                "taskId": "resting-recording",
                "kind": "reviewed_recording",
                "capability": "brainstem.recording.resting-rr.reviewed.v1",
                "windowStartDay": 0,
                "windowEndDay": 14,
                "cadenceDays": 1,
                "maximumOccurrences": 14,
                "completionPolicy": "source_recording",
                "burdenMinutes": 5,
                "reminderPolicy": {
                    "enabled": False,
                    "earliestOffsetMinutes": 0,
                    "maximumCount": 0,
                },
            }
        ],
    },
)

_COMMUNITY_SURVEY = _artifact(
    "survey",
    "brainstem.community-health-questionnaire-survey",
    {
        "questions": [
            _question(
                "health_priority",
                "Which area would you most like future wellbeing research to explore?",
                ("activity", "heart_health", "sleep", "stress", "prefer_not_to_say"),
            ),
            _question(
                "follow_up_interest",
                "Would you like to see future voluntary studies about that area?",
                ("no", "unsure", "yes"),
                required=False,
            ),
        ],
        "freeTextAllowed": False,
        "evidenceSource": "participant_self_report",
        "clinicalVerification": False,
    },
)
_COMMUNITY_PURPOSE = _artifact(
    "purpose",
    "brainstem.community-health-questionnaire-purpose",
    {
        "purpose": "Learn which non-diagnostic wellbeing research topics the community would value.",
        "historicalDataUse": False,
        "resultReturn": "A disclosure-safe topic summary may guide future candidate studies.",
        "evidenceLabel": "Voluntary preferences only; responses are not clinical evidence.",
    },
)
_COMMUNITY_INFORMATION = _artifact(
    "participant_information",
    "brainstem.community-health-questionnaire-information",
    {
        "text": "This optional generated-only questionnaire asks about research priorities. Answering does not join a study or authorize device-data use.",
        "retention": "Versioned answers remain until deletion under this candidate local policy.",
        "withdrawal": "You may stop participating without changing any separate Brainstem choices.",
        "deletion": "Deleting removes answer content, leaves a content-free tombstone, and excludes the response from future summaries.",
        "status": "candidate_generated_only",
    },
)

_APDET_PURPOSE = _artifact(
    "purpose",
    "brainstem.apdet-retrospective-purpose",
    {
        "purpose": "Check whether eligible full-night Brainstem detector R-R recordings satisfy the reviewed signal-quality and input-compatibility contract.",
        "historicalDataUse": True,
        "resultReturn": "Only a privacy-checked aggregate methods result may be returned.",
        "evidenceLabel": "This is non-clinical methods research, not sleep-apnea screening, diagnosis, reassurance, or personal advice.",
    },
)
_APDET_INFORMATION = _artifact(
    "participant_information",
    "brainstem.apdet-retrospective-information",
    {
        "text": "This retrospective study uses at most one existing qualifying full-night recording per currently consenting participant and creates no participant-level study copy.",
        "retention": "Temporary compute input is deleted after the bounded job. A released non-identifying aggregate and content-free provenance may remain for reproducibility.",
        "withdrawal": "Withdrawal or consent revocation excludes the participant from every future materialization.",
        "deletion": "Source deletion excludes the recording from every future materialization and does not rewrite a previously released non-identifying aggregate.",
        "status": "candidate_real_cohort",
    },
)
_APDET_PROTOCOL = _artifact(
    "protocol",
    "brainstem.apdet-retrospective-protocol",
    {
        "population": "Current members of the exact purpose-bound cohort release who retain both data-consent flags and one qualifying full-night sleep recording.",
        "burden": "No new participant task, contact, intervention, survey, notification, or recording.",
        "schedule": "One operator-authorized retrospective aggregate run.",
        "endpoints": "Disclosure-safe cohort band and aggregate full-night duration, accepted-interval fraction, interval-duration coverage, and explicit normal-to-normal provenance abstention.",
        "analysisPlan": "Select at most one latest qualifying recording per participant, enforce the post-filter twenty-participant disclosure floor, and run only the immutable network-disabled signal-compatibility algorithm.",
    },
)
_APDET_DATASET = _artifact(
    "dataset_view",
    "brainstem.apdet-retrospective-dataset",
    {
        "schema": "brainstem.full-night-rr-cohort.v1",
        "policy": "brainstem.full-night-rr-signal-compatibility.v1",
        "adapterCapability": "brainstem.study-export.full-night-rr-signal-compatibility.v1",
        "sourceDefined": True,
        "fieldsCallerSelectable": False,
    },
)
_APDET_ACTIVATION = _artifact(
    "activation_profile",
    "brainstem.apdet-retrospective-activation",
    {
        "profileId": "brainstem.apdet-retrospective.real-cohort",
        "datasetCapability": "brainstem.study-export.full-night-rr-signal-compatibility.v1",
        "algorithmId": "brainstem.full-night-signal-compatibility",
        "algorithmVersion": "0.1.0",
        "algorithmSourceSha256": "834e226745b78831383efa6b20b5fd0cb9b5660d84b1c357beec638b3857bf3c",
        "algorithmImageDigest": "sha256:67862058656d6d492e03b854ed751324a0f10fe8d1a239aecc6e4cb7b35c3d70",
        "approvedManifestSha256": "066174b1a511c60590cbd65f98abd3c2787864bb5297832670ae88365df4fd89",
        "referenceSha256": "b4961dae0e5bded52a2caecf6bcc186837d4deccf1ac2f173c9f6d5f0a376eac",
        "resultContractId": "brainstem.c2d-result.v1",
        "resultContractSha256": "9cacdaa78ce534d45853e3ffd10b30a19faf30b1e5a1251e5ac74c03b0ad0dbd",
        "operationalPolicyId": "brainstem.study-operations.mtls-local-ocean.v1",
        "operationalPolicySha256": content_sha256(
            {
                "transport": "mtls_over_authenticated_ssh",
                "algorithmNetwork": "none",
                "singleFetch": True,
                "temporaryInput": True,
                "resultMode": "aggregate_only",
            }
        ),
        "environment": "brainstem-ocean-real-cohort",
        "dataMode": "real_cohort",
        "algorithmNetwork": "none",
        "limits": {
            "minimumParticipants": 20,
            "maximumParticipants": 100,
            "maximumRecordingsPerParticipant": 1,
            "maximumTotalRecordings": 100,
            "maximumInputBytes": 16777216,
            "maximumResultBytes": 262144,
            "maximumJobDurationSeconds": 60,
        },
        "permitTtlSeconds": 86400,
        "payment": {"currency": "none", "amountMinor": 0},
    },
)

_APDET_DIAGNOSIS_SURVEY = _artifact(
    "survey",
    "brainstem.apdet-retrospective-diagnosis-survey",
    {
        "questions": [
            _question(
                "sleep_apnea_diagnosis",
                "Has a qualified healthcare professional diagnosed you with sleep apnea?",
                ("no", "prefer_not_to_say", "unsure", "yes"),
                required=False,
            ),
            _question(
                "hypertension_diagnosis",
                "Has a qualified healthcare professional diagnosed you with high blood pressure?",
                ("no", "prefer_not_to_say", "unsure", "yes"),
                required=False,
            ),
            _question(
                "heart_rhythm_diagnosis",
                "Has a qualified healthcare professional diagnosed you with atrial fibrillation or another persistent heart-rhythm condition?",
                ("no", "prefer_not_to_say", "unsure", "yes"),
                required=False,
            ),
            _question(
                "type_2_diabetes_diagnosis",
                "Has a qualified healthcare professional diagnosed you with type 2 diabetes?",
                ("no", "prefer_not_to_say", "unsure", "yes"),
                required=False,
            ),
            _question(
                "chronic_respiratory_diagnosis",
                "Has a qualified healthcare professional diagnosed you with a chronic breathing or lung condition?",
                ("no", "prefer_not_to_say", "unsure", "yes"),
                required=False,
            ),
            _question(
                "other_chronic_disease_diagnosis",
                "Has a qualified healthcare professional diagnosed you with another chronic disease?",
                ("no", "prefer_not_to_say", "unsure", "yes"),
                required=False,
            ),
        ],
        "freeTextAllowed": False,
        "evidenceSource": "participant_self_report",
        "clinicalVerification": False,
    },
)
_APDET_DIAGNOSIS_PURPOSE = _artifact(
    "purpose",
    "brainstem.apdet-retrospective-diagnosis-purpose",
    {
        "purpose": "Collect optional diagnosis context from members of the full-night signal compatibility study to guide and evaluate future non-diagnostic chronic-disease methods.",
        "historicalDataUse": False,
        "resultReturn": "Only disclosure-safe aggregate research context may be used in reviewed study results.",
        "evidenceLabel": "Self-reported diagnosis context is not clinically verified ground truth and cannot diagnose, screen, reassure, or provide medical advice.",
    },
)
_APDET_DIAGNOSIS_INFORMATION = _artifact(
    "participant_information",
    "brainstem.apdet-retrospective-diagnosis-information",
    {
        "text": "This optional questionnaire is available only to current members of the first Brainstem full-night study. Each question may be skipped. Answering does not change your study membership or data-sharing choice.",
        "retention": "Versioned answers remain purpose-bound to this study until you delete them.",
        "withdrawal": "Leaving the study or losing current study membership prevents further access and future use of the answers.",
        "deletion": "Deleting removes answer content, leaves a content-free tombstone, and excludes the response from future analysis.",
        "status": "candidate_real_cohort",
    },
)


def _validate_recording_answers(answers):
    if (
        answers.get("chronic_condition_status") == "no"
        and answers.get("clinician_confirmation_status") == "yes"
    ):
        raise StudyRegistryError("survey_answers_contradictory")


_RECORDING_RELEASE = make_release(
    RECORDING_FEASIBILITY_ID,
    "study",
    "1.0.0",
    title="Everyday resting recording study",
    summary="A generated-only fourteen-day feasibility study using ordinary resting recordings.",
    purpose=_STUDY_PURPOSE,
    survey=_STUDY_SURVEY,
    participant_information=_STUDY_INFORMATION,
    protocol=_STUDY_PROTOCOL,
    dataset_view=_STUDY_DATASET,
    activation_profile=_STUDY_ACTIVATION_PROFILE,
    task_plan=_STUDY_TASK_PLAN,
    data_union_id=DATA_UNION_ID,
)
_COMMUNITY_RELEASE = make_release(
    COMMUNITY_QUESTIONNAIRE_ID,
    "community_questionnaire",
    "1.0.0",
    title="Community wellbeing priorities",
    summary="An optional generated-only questionnaire about future research topics.",
    purpose=_COMMUNITY_PURPOSE,
    survey=_COMMUNITY_SURVEY,
    participant_information=_COMMUNITY_INFORMATION,
    data_union_id=DATA_UNION_ID,
)
_APDET_RELEASE = make_release(
    APDET_RETROSPECTIVE_ID,
    "retrospective_study",
    "1.0.0",
    title="Full-night signal compatibility study",
    summary="A one-run retrospective aggregate check of full-night detector R-R signal quality and method-input compatibility.",
    purpose=_APDET_PURPOSE,
    participant_information=_APDET_INFORMATION,
    protocol=_APDET_PROTOCOL,
    dataset_view=_APDET_DATASET,
    activation_profile=_APDET_ACTIVATION,
    data_union_id=DATA_UNION_ID,
)
_APDET_DIAGNOSIS_RELEASE = make_release(
    APDET_DIAGNOSIS_QUESTIONNAIRE_ID,
    "community_questionnaire",
    "1.0.0",
    title="First study health context",
    summary="Optional chronic-disease diagnosis context for members of the full-night signal compatibility study.",
    purpose=_APDET_DIAGNOSIS_PURPOSE,
    survey=_APDET_DIAGNOSIS_SURVEY,
    participant_information=_APDET_DIAGNOSIS_INFORMATION,
    data_union_id=DATA_UNION_ID,
)

APDET_RETROSPECTIVE_RELEASE_SHA256 = _APDET_RELEASE["releaseSha256"]
APDET_DIAGNOSIS_QUESTIONNAIRE_RELEASE_SHA256 = _APDET_DIAGNOSIS_RELEASE[
    "releaseSha256"
]

DEFAULT_STUDY_REGISTRY = StudyRegistry(
    [
        _STUDY_SURVEY,
        _STUDY_PURPOSE,
        _STUDY_INFORMATION,
        _STUDY_PROTOCOL,
        _STUDY_DATASET,
        _STUDY_ACTIVATION_PROFILE,
        _STUDY_TASK_PLAN,
        _COMMUNITY_SURVEY,
        _COMMUNITY_PURPOSE,
        _COMMUNITY_INFORMATION,
        _APDET_PURPOSE,
        _APDET_INFORMATION,
        _APDET_PROTOCOL,
        _APDET_DATASET,
        _APDET_ACTIVATION,
        _APDET_DIAGNOSIS_SURVEY,
        _APDET_DIAGNOSIS_PURPOSE,
        _APDET_DIAGNOSIS_INFORMATION,
    ],
    [
        _RECORDING_RELEASE,
        _COMMUNITY_RELEASE,
        _APDET_RELEASE,
        _APDET_DIAGNOSIS_RELEASE,
    ],
    answer_validators={RECORDING_FEASIBILITY_ID: _validate_recording_answers},
)
