import hmac
import json
import os
import re
from datetime import timedelta
from pathlib import Path

from flask import Blueprint, Response, jsonify, request

from commands.dataunions.brainstem.c2d_export import (
    BrainstemC2DExporter,
    C2DExportError,
    FULL_NIGHT_COMPATIBILITY_POLICY,
    JOB_ID_PATTERN,
    cohort_insight_policy,
)
from commands.dataunions.brainstem.cohort_release import (
    CohortReleaseError,
    CohortReleaseService,
    RELEASE_ID_PATTERN,
)
from commands.dataunions.brainstem.cohort_reference import (
    CohortReferenceError,
    CohortReferenceService,
)
from commands.dataunions.brainstem.value_commit import (
    BrainstemValueService,
    ValueCommitError,
)
from commands.dataunions.brainstem.study_proposals import (
    StudyProposalError,
    normalize_proposal_id,
    reviewed_revision_binding,
)
from commands.dataunions.brainstem.study_data_authorization import (
    StudyDataAuthorizationError,
)
from config import config
from dao.cohort_release_dao import cohort_release_dao
from dao.metadata_dao import image_metadata_dao
from dao.users_dao import user_dao
from dao.rewards_dao import rewards_dao
from dao.study_proposal_dao import study_proposal_dao
from routes.generic_study_routes import _data_authorization_service


brainstem_c2d_routes = Blueprint("brainstem_c2d_routes", __name__)
REFERENCE_ANALYSES = {
    "resting-hrv-methods": "brainstem.resting-hrv-methods/v1",
    "resting-rr-sample-entropy": "brainstem.resting-rr-sample-entropy/v1",
}


def _setting(name: str) -> str:
    if not config.has_section("brainstem_c2d"):
        return ""
    return config["brainstem_c2d"].get(name, "").strip()


def _integer_setting(name: str, default: int) -> int:
    value = _setting(name)
    if not value:
        return default
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise CohortReleaseError("release_configuration_invalid", 503) from exc


def _valid_secret(value: str) -> bool:
    return len(value) >= 32 and not value.startswith("<")


def _value_setting(name: str) -> str:
    if not config.has_section("brainstem_value"):
        return ""
    return config["brainstem_value"].get(name, "").strip()


def _value_enabled() -> bool:
    return config.has_section("brainstem_value") and config[
        "brainstem_value"
    ].getboolean("enabled", fallback=False)


def _value_service():
    if not _value_enabled():
        return None
    try:
        amount = config["brainstem_value"].getint("amount")
    except (ValueError, TypeError) as exc:
        raise ValueCommitError("value_configuration_invalid", 503) from exc
    return BrainstemValueService(
        rewards_dao=rewards_dao,
        metadata_dao=image_metadata_dao,
        users_dao=user_dao,
        release_dao=cohort_release_dao,
        consent_version=_setting("consent_version"),
        amount=amount,
        approved_algorithm_digest=_value_setting("approved_algorithm_digest"),
        expected_node_signer=_value_setting("node_signer_address"),
        signing_private_key=_value_setting("signing_private_key"),
    )


def _authorized(token: str) -> bool:
    authorization = request.headers.get("Authorization", "")
    return _valid_secret(token) and hmac.compare_digest(
        authorization, f"Bearer {token}"
    )


def _release_service() -> CohortReleaseService:
    return CohortReleaseService(
        release_dao=cohort_release_dao,
        users_dao=user_dao,
        consent_version=_setting("consent_version"),
        metadata_dao=image_metadata_dao,
        refresh_min_contributors=_integer_setting("refresh_min_contributors", 20),
        refresh_min_age=timedelta(hours=_integer_setting("refresh_min_age_hours", 168)),
    )


def _reference_service() -> CohortReferenceService:
    return CohortReferenceService(cohort_release_dao, _release_service())


def _reference_analysis(slug: str) -> str:
    try:
        return REFERENCE_ANALYSES[slug]
    except KeyError as exc:
        raise CohortReferenceError("reference_analysis_invalid", 404) from exc


def _reference_error(exc: CohortReferenceError):
    message = "Service unavailable" if exc.status_code >= 500 else "Reference rejected"
    return jsonify({"status": "failed", "message": message}), exc.status_code


def _release_error(exc: CohortReleaseError):
    message = "Service unavailable" if exc.status_code >= 500 else "Release rejected"
    return jsonify({"status": "failed", "message": message}), exc.status_code


def _operator_body(expected_keys):
    if request.content_length is not None and request.content_length > 64 * 1024:
        raise CohortReleaseError("release_request_too_large", 413)
    body = request.get_json(silent=True)
    if not isinstance(body, dict) or set(body) != set(expected_keys):
        raise CohortReleaseError("release_request_invalid", 400)
    return body


def _refresh_response(result):
    response = jsonify(result)
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


@brainstem_c2d_routes.route("/api/v1/internal/c2d/cohort-releases", methods=["POST"])
def create_cohort_release():
    if not _authorized(_setting("release_admin_bearer_token")):
        return jsonify({"status": "failed", "message": "Unauthorized"}), 401
    try:
        body = _operator_body({"rosterUserIds", "expiresAt"})
        release = _release_service().create(body["rosterUserIds"], body["expiresAt"])
    except CohortReleaseError as exc:
        return _release_error(exc)
    except Exception:
        return jsonify({"status": "failed", "message": "Service unavailable"}), 503
    return (
        jsonify(
            {
                "releaseId": release["release_id"],
                "status": release["status"],
                "expiresAt": release["expires_at"],
            }
        ),
        201,
    )


@brainstem_c2d_routes.route(
    "/api/v1/internal/c2d/cohort-releases/<release_id>/activate",
    methods=["POST"],
)
def activate_cohort_release(release_id):
    if not _authorized(_setting("release_admin_bearer_token")):
        return jsonify({"status": "failed", "message": "Unauthorized"}), 401
    try:
        body = _operator_body({"approvalReference"})
        release = _release_service().activate(release_id, body["approvalReference"])
    except CohortReleaseError as exc:
        return _release_error(exc)
    except Exception:
        return jsonify({"status": "failed", "message": "Service unavailable"}), 503
    return (
        jsonify(
            {
                "releaseId": release["release_id"],
                "status": release["status"],
                "expiresAt": release["expires_at"],
            }
        ),
        200,
    )


@brainstem_c2d_routes.route(
    "/api/v1/internal/c2d/cohort-releases/<release_id>/revoke",
    methods=["POST"],
)
def revoke_cohort_release(release_id):
    if not _authorized(_setting("release_admin_bearer_token")):
        return jsonify({"status": "failed", "message": "Unauthorized"}), 401
    try:
        body = _operator_body({"reasonReference"})
        release = _release_service().revoke(release_id, body["reasonReference"])
    except CohortReleaseError as exc:
        return _release_error(exc)
    except Exception:
        return jsonify({"status": "failed", "message": "Service unavailable"}), 503
    return (
        jsonify(
            {
                "releaseId": release["release_id"],
                "status": release["status"],
                "expiresAt": release["expires_at"],
            }
        ),
        200,
    )


@brainstem_c2d_routes.route(
    "/api/v1/internal/c2d/cohort-releases/<release_id>/refresh",
    methods=["GET"],
)
def cohort_release_refresh_status(release_id):
    if not _authorized(_setting("refresh_status_bearer_token")):
        return jsonify({"status": "failed", "message": "Unauthorized"}), 401
    try:
        result = _release_service().refresh_status(release_id)
    except CohortReleaseError as exc:
        return _release_error(exc)
    except Exception:
        return jsonify({"status": "failed", "message": "Service unavailable"}), 503
    return _refresh_response(result), 200


@brainstem_c2d_routes.route(
    "/api/v1/internal/c2d/cohort-releases/<release_id>/refresh/evaluate",
    methods=["POST"],
)
def evaluate_cohort_release_refresh(release_id):
    if not _authorized(_setting("release_admin_bearer_token")):
        return jsonify({"status": "failed", "message": "Unauthorized"}), 401
    if request.content_length not in {None, 0}:
        return jsonify({"status": "failed", "message": "Release rejected"}), 400
    try:
        result = _release_service().evaluate_refresh(release_id)
    except CohortReleaseError as exc:
        return _release_error(exc)
    except Exception:
        return jsonify({"status": "failed", "message": "Service unavailable"}), 503
    return _refresh_response(result), 200


@brainstem_c2d_routes.route(
    "/api/v1/internal/c2d/cohort-references/<analysis_slug>",
    methods=["POST"],
)
def draft_cohort_reference(analysis_slug):
    if not _authorized(_setting("release_admin_bearer_token")):
        return jsonify({"status": "failed", "message": "Unauthorized"}), 401
    try:
        body = _operator_body(
            {
                "referenceSha256",
                "artifactSha256",
                "version",
                "sourceReleaseId",
                "algorithmImageDigest",
                "approvedManifestSha256",
                "supersedes",
            }
        )
        reference = _reference_service().draft(
            analysis_id=_reference_analysis(analysis_slug),
            reference_sha256=body["referenceSha256"],
            artifact_sha256=body["artifactSha256"],
            version=body["version"],
            source_release_id=body["sourceReleaseId"],
            algorithm_image_digest=body["algorithmImageDigest"],
            approved_manifest_sha256=body["approvedManifestSha256"],
            supersedes=body["supersedes"],
        )
    except CohortReleaseError as exc:
        return _release_error(exc)
    except CohortReferenceError as exc:
        return _reference_error(exc)
    except Exception:
        return jsonify({"status": "failed", "message": "Service unavailable"}), 503
    return jsonify({"result": reference}), 201


def _transition_reference(analysis_slug, reference_id, action):
    if not _authorized(_setting("release_admin_bearer_token")):
        return jsonify({"status": "failed", "message": "Unauthorized"}), 401
    field = "reviewReference" if action == "activate" else "reasonReference"
    try:
        body = _operator_body({field})
        service = _reference_service()
        result = getattr(service, action)(
            _reference_analysis(analysis_slug), reference_id, body[field]
        )
    except CohortReleaseError as exc:
        return _release_error(exc)
    except CohortReferenceError as exc:
        return _reference_error(exc)
    except Exception:
        return jsonify({"status": "failed", "message": "Service unavailable"}), 503
    return jsonify({"result": result}), 200


@brainstem_c2d_routes.route(
    "/api/v1/internal/c2d/cohort-references/<analysis_slug>/<reference_id>/activate",
    methods=["POST"],
)
def activate_cohort_reference(analysis_slug, reference_id):
    return _transition_reference(analysis_slug, reference_id, "activate")


@brainstem_c2d_routes.route(
    "/api/v1/internal/c2d/cohort-references/<analysis_slug>/<reference_id>/withdraw",
    methods=["POST"],
)
def withdraw_cohort_reference(analysis_slug, reference_id):
    return _transition_reference(analysis_slug, reference_id, "withdraw")


@brainstem_c2d_routes.route(
    "/api/v1/internal/c2d/cohort-references/<analysis_slug>/<reference_id>/delete",
    methods=["POST"],
)
def delete_cohort_reference(analysis_slug, reference_id):
    return _transition_reference(analysis_slug, reference_id, "delete")


@brainstem_c2d_routes.route(
    "/api/v1/c2d/cohort-references/<analysis_slug>", methods=["GET"]
)
def cohort_reference_status(analysis_slug):
    try:
        result = _reference_service().public_projection(
            _reference_analysis(analysis_slug)
        )
    except CohortReferenceError as exc:
        return _reference_error(exc)
    except Exception:
        return jsonify({"status": "failed", "message": "Service unavailable"}), 503
    return _refresh_response({"result": result}), 200


@brainstem_c2d_routes.route("/api/v1/internal/c2d/rr-cohort", methods=["GET"])
def export_rr_cohort():
    bearer_token = _setting("export_bearer_token")
    pseudonym_secret = _setting("pseudonym_secret")
    pseudonym_key_id = _setting("pseudonym_key_id")
    if (
        not _valid_secret(bearer_token)
        or not _valid_secret(pseudonym_secret)
        or not isinstance(pseudonym_key_id, str)
        or not pseudonym_key_id
    ):
        return jsonify({"status": "failed", "message": "Service unavailable"}), 503

    if not _authorized(bearer_token):
        return jsonify({"status": "failed", "message": "Unauthorized"}), 401

    job_id = request.headers.get("X-Ocean-Compute-Job-Id", "")
    if not JOB_ID_PATTERN.fullmatch(job_id):
        return jsonify({"status": "failed", "message": "Invalid compute job"}), 400
    release_id = request.headers.get("X-Brainstem-Cohort-Release-Id", "")
    if not RELEASE_ID_PATTERN.fullmatch(release_id):
        return jsonify({"status": "failed", "message": "Invalid release"}), 400
    try:
        policy = cohort_insight_policy(
            request.headers.get("X-Brainstem-Analysis-Id", "")
        )
    except C2DExportError:
        return jsonify({"status": "failed", "message": "Invalid analysis"}), 400

    study_binding = None
    if policy.analysis_id == FULL_NIGHT_COMPATIBILITY_POLICY.analysis_id:
        governed_release_id = os.environ.get(
            "BRAINSTEM_STUDY_ELIGIBILITY_RELEASE_ID", ""
        )
        study_release_version = os.environ.get(
            "BRAINSTEM_STUDY_RELEASE_VERSION", ""
        )
        study_release_sha256 = os.environ.get("BRAINSTEM_STUDY_RELEASE_SHA256", "")
        if (
            not RELEASE_ID_PATTERN.fullmatch(governed_release_id)
            or not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", study_release_version)
            or not re.fullmatch(r"[0-9a-f]{64}", study_release_sha256)
        ):
            return jsonify({"status": "failed", "message": "Service unavailable"}), 503
        if not hmac.compare_digest(release_id, governed_release_id):
            return jsonify({"status": "failed", "message": "Invalid release"}), 400
        try:
            proposal_id = request.headers.get("X-Brainstem-Study-Proposal-Id", "")
            normalize_proposal_id(proposal_id)
            study_binding = reviewed_revision_binding(
                study_proposal_dao.get(proposal_id),
                proposal_id,
                request.headers.get("X-Brainstem-Study-Revision-Id", ""),
                request.headers.get("X-Brainstem-Study-Revision-SHA256", ""),
                "brainstem.apdet-retrospective-study",
                study_release_version,
                study_release_sha256,
            )
        except StudyProposalError as exc:
            return (
                jsonify({"status": "failed", "message": "Study review required"}),
                exc.status_code,
            )
        except Exception:
            return jsonify({"status": "failed", "message": "Service unavailable"}), 503

    upload_folder = config["application"].get("upload_folder", "data")
    upload_root = Path(upload_folder)
    if not upload_root.is_absolute():
        upload_root = Path.cwd() / upload_root
    try:
        value_service = _value_service() if policy.value_enabled else None
    except ValueCommitError:
        return jsonify({"status": "failed", "message": "Service unavailable"}), 503
    exporter = BrainstemC2DExporter(
        metadata_dao=image_metadata_dao,
        users_dao=user_dao,
        audit_dao=image_metadata_dao,
        release_dao=cohort_release_dao,
        upload_root=upload_root,
        pseudonym_secret=pseudonym_secret,
        pseudonym_key_id=pseudonym_key_id,
        consent_version=_setting("consent_version"),
        value_service=value_service,
        policy=policy,
    )
    authorization_receipt = None
    try:
        if study_binding is not None:
            proposal_id = request.headers.get("X-Brainstem-Study-Proposal-Id", "")
            permit_id = request.headers.get(
                "X-Brainstem-Study-Data-Permit-Id", ""
            )

            def execute_study(binding):
                if (
                    binding["proposalId"] != proposal_id
                    or binding["revisionId"] != study_binding["revisionId"]
                    or binding["revisionSha256"]
                    != study_binding["revisionSha256"]
                    or binding["cohortReleaseId"] != release_id
                ):
                    raise StudyDataAuthorizationError(
                        "study_data_compute_binding_invalid", 409
                    )
                return exporter.execute(job_id, release_id, study_binding)

            artifact, authorization_receipt = _data_authorization_service().execute(
                proposal_id,
                permit_id,
                "compute",
                job_id,
                execute_study,
            )
        else:
            artifact = exporter.execute(job_id, release_id)
    except C2DExportError as exc:
        message = "Export unavailable" if exc.status_code >= 500 else "Export rejected"
        return jsonify({"status": "failed", "message": message}), exc.status_code
    except StudyDataAuthorizationError as exc:
        message = (
            "Service unavailable" if exc.status_code >= 500 else "Export rejected"
        )
        return jsonify({"status": "failed", "message": message}), exc.status_code

    response = Response(artifact.body, status=200, mimetype="application/json")
    response.headers["Content-Length"] = str(len(artifact.body))
    response.headers["X-Content-SHA256"] = artifact.checksum
    response.headers["X-Brainstem-Pseudonym-Key-Id"] = artifact.pseudonym_key_id
    source_snapshot_sha256 = getattr(artifact, "source_snapshot_sha256", None)
    if (
        policy.analysis_id == FULL_NIGHT_COMPATIBILITY_POLICY.analysis_id
        and source_snapshot_sha256
    ):
        response.headers[
            "X-Brainstem-Source-Snapshot-SHA256"
        ] = source_snapshot_sha256
    if authorization_receipt is not None:
        response.headers[
            "X-Brainstem-Study-Authorization-Receipt-SHA256"
        ] = authorization_receipt["receiptSha256"]
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


@brainstem_c2d_routes.route("/api/v1/internal/c2d/value-commit", methods=["POST"])
def commit_participant_value():
    if not _authorized(_setting("export_bearer_token")):
        return jsonify({"status": "failed", "message": "Unauthorized"}), 401
    if request.content_length is not None and request.content_length > 16 * 1024:
        return jsonify({"status": "failed", "message": "Invalid receipt"}), 413
    if not request.is_json:
        return jsonify({"status": "failed", "message": "Invalid receipt"}), 400
    try:
        raw_body = request.stream.read(16 * 1024 + 1)
        if len(raw_body) > 16 * 1024:
            return jsonify({"status": "failed", "message": "Invalid receipt"}), 413
        body = json.loads(raw_body)
    except (UnicodeError, json.JSONDecodeError):
        return jsonify({"status": "failed", "message": "Invalid receipt"}), 400
    if not isinstance(body, dict) or set(body) != {"receipt", "signature"}:
        return jsonify({"status": "failed", "message": "Invalid receipt"}), 400
    try:
        service = _value_service()
        if service is None:
            raise ValueCommitError("value_disabled", 503)
        commitment = service.commit(body["receipt"], body["signature"])
    except ValueCommitError as exc:
        message = (
            "Service unavailable" if exc.status_code >= 500 else "Receipt rejected"
        )
        return jsonify({"status": "failed", "message": message}), exc.status_code
    except Exception:
        return jsonify({"status": "failed", "message": "Service unavailable"}), 503
    return jsonify({"commitment": commitment}), 200
