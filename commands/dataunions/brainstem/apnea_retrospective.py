"""Immutable candidate protocol for the dormant retrospective apnea-method study."""

import hashlib
import json


STUDY_ID = "brainstem.apdet-retrospective-study"
PROTOCOL_VERSION = "1.0.0"
ANALYSIS_ID = "brainstem.apdet-retrospective-evidence/v1"
DATASET_SCHEMA = "brainstem.full-night-rr-cohort/v1"
DATASET_POLICY = "brainstem.apdet-retrospective/v1"
MINIMUM_PARTICIPANTS = 20
OFFICIAL_SOURCE_SHA256 = (
    "b4961dae0e5bded52a2caecf6bcc186837d4deccf1ac2f173c9f6d5f0a376eac"
)
PUBLIC_EVALUATION_PLAN_SHA256 = (
    "44ed0e698e21dcb683e332e90b50756a19c28954b7c30c2c80a1a2ac1fdb3d68"
)


def candidate_protocol():
    return {
        "schema": "brainstem.retrospective-aggregate-study/v1",
        "status": "candidate_generated_only",
        "studyId": STUDY_ID,
        "protocolVersion": PROTOCOL_VERSION,
        "purpose": "Evaluate whether an externally reviewed heart-rate-dynamics method is technically compatible with existing consenting Brainstem sleep recordings.",
        "design": "Retrospective aggregate methods study with no recruitment, intervention, participant task, survey, notification, payment, or personal result.",
        "population": "Current members of a separately approved purpose-bound Brainstem cohort release who still have both required data-consent flags and one qualifying sleep recording.",
        "selection": "At materialization time, revalidate the current release, consent, source document, content hash, and file; then select the latest qualifying full-night recording per participant by capture time, envelope time, content hash, and source identifier.",
        "method": {
            "paperDoi": "10.1109/CIC.2000.898634",
            "officialSourceSha256": OFFICIAL_SOURCE_SHA256,
            "publicEvaluationPlanSha256": PUBLIC_EVALUATION_PLAN_SHA256,
            "sourceLicence": "GPL-2.0-or-later embedded notices; redistribution and deployment require human licence review",
            "executionStatus": "blocked_pending_public_evidence_and_licence_review",
        },
        "input": {
            "schema": DATASET_SCHEMA,
            "policy": DATASET_POLICY,
            "recordType": "sleep",
            "payload": "hbr_rr",
            "durationSeconds": [18000, 43200],
            "minimumValidIntervals": 9000,
            "maximumIntervals": 172800,
            "minimumValidFraction": 0.95,
            "intervalDurationCoverageRatio": [0.9, 1.1],
            "intervalSemantics": "detector_rr_unclassified",
        },
        "privacy": {
            "minimumDistinctParticipants": MINIMUM_PARTICIPANTS,
            "identity": "study-domain, job-scoped HMAC pseudonym only",
            "participantWalletVisible": False,
            "sourceIdentifierVisible": False,
            "rawDownload": False,
        },
        "retention": "Source recordings remain governed by their existing retention terms. Temporary job input is deleted by the compute policy. Completed non-identifying aggregate evidence may be retained for reproducibility.",
        "withdrawalAndDeletion": "Current withdrawal, consent revocation, release removal, or source deletion excludes the participant or record from every future materialization. It does not rewrite a previously released non-identifying aggregate result.",
        "analysis": {
            "analysisId": ANALYSIS_ID,
            "officialMethodInputMismatch": "Brainstem R-R intervals are not proven normal-to-normal intervals.",
            "personalResult": False,
            "diagnosis": False,
            "screening": False,
            "ahi": False,
            "medicalAdvice": False,
        },
        "activation": {
            "generatedDataOnly": True,
            "liveStudy": False,
            "recurrence": False,
            "notifications": False,
            "payment": False,
            "rewards": False,
        },
    }


def protocol_sha256():
    return hashlib.sha256(
        json.dumps(
            candidate_protocol(), sort_keys=True, separators=(",", ":")
        ).encode()
    ).hexdigest()
