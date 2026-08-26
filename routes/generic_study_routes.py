import json
import hmac
import os
from pathlib import Path
import re

from flask import Blueprint, jsonify, request
from flask_jwt_extended import get_jwt, get_jwt_identity, jwt_required

from commands.dataunions.brainstem.generic_study_service import (
    GenericStudyService,
    GenericStudyServiceError,
    PendingAnswerStore,
)
from commands.dataunions.brainstem.study_proposals import (
    QUEUE_STATES,
    StudyProposalError,
    StudyProposalForbidden,
    StudyProposalNotFound,
    StudyProposalPayloadTooLarge,
    StudyProposalWorkflow,
    parse_page,
)
from commands.dataunions.brainstem.c2d_export import (
    FULL_NIGHT_COMPATIBILITY_POLICY,
    BrainstemC2DExporter,
)
from commands.dataunions.brainstem.cohort_release import (
    CohortReleaseError,
    CohortReleaseService,
)
from commands.dataunions.brainstem.consent import has_brainstem_data_consent
from commands.dataunions.brainstem.study_eligibility import StudyEligibilityPreview
from commands.dataunions.brainstem.study_results import (
    StudyResultError,
    StudyResultService,
)
from commands.dataunions.brainstem.study_activation import (
    StudyActivationError,
    StudyActivationService,
)
from commands.dataunions.brainstem.study_data_authorization import (
    StudyDataAuthorizationError,
    StudyDataAuthorizationService,
)
from commands.dataunions.brainstem.study_operations import (
    StudyOperationsMetricsSource,
    StudyOperationsError,
    StudyOperationsService,
)
from commands.dataunions.brainstem.study_recurring import (
    StudyRecurringError,
    StudyRecurringService,
)
from commands.dataunions.brainstem.study_registry import (
    APDET_DIAGNOSIS_QUESTIONNAIRE_ID,
    APDET_DIAGNOSIS_QUESTIONNAIRE_RELEASE_SHA256,
    DEFAULT_STUDY_REGISTRY,
)
from commands.dataunions.studies.registry import (
    StudyRegistryError,
)
from config import config
from commands.users.participant_auth import ParticipantAuthError
from dao.base_dao import DBResultError
from dao.study_dao import study_dao
from dao.study_activation_dao import study_activation_dao
from dao.study_operations_dao import study_operations_dao
from dao.study_proposal_dao import study_proposal_dao
from dao.study_result_dao import study_result_dao
from dao.cohort_release_dao import cohort_release_dao
from dao.metadata_dao import image_metadata_dao
from dao.users_dao import user_dao
from routes.participant_auth_routes import _service as participant_auth_service


MAX_BODY_BYTES = 32 * 1024
MAX_STUDY_RESULT_BODY_BYTES = 320 * 1024
generic_study_routes = Blueprint("generic_study_routes", __name__)
study_proposal_workflow = StudyProposalWorkflow(study_proposal_dao)
pending_answer_store = PendingAnswerStore()


def _configured():
    return (
        config.has_section("brainstem_generic_studies")
        and config["brainstem_generic_studies"].getboolean(
            "enabled", fallback=False
        )
    )


def _enabled():
    return _configured() and config["brainstem_generic_studies"].getboolean(
        "generated_only", fallback=False
    )


def _require_enabled():
    if not _enabled():
        raise GenericStudyServiceError("generic_studies_disabled", 503)


def _participant_enabled():
    return (
        _configured()
        and config.has_section("brainstem_studies")
        and config["brainstem_studies"].getboolean("enabled", fallback=False)
        and (
            _enabled()
            or _member_survey_enabled()
        )
    )


def _member_survey_enabled():
    return (
        os.environ.get("BRAINSTEM_STUDY_MEMBER_SURVEYS_ENABLED") == "true"
        and os.environ.get("BRAINSTEM_STUDY_MEMBER_SURVEY_RELEASE_SHA256")
        == APDET_DIAGNOSIS_QUESTIONNAIRE_RELEASE_SHA256
    )


def _require_participant_enabled():
    if not _participant_enabled():
        raise GenericStudyServiceError("participant_studies_disabled", 503)


def _operator_enabled():
    return _configured() and config["brainstem_generic_studies"].getboolean(
        "operator_operations_enabled", fallback=False
    )


def _recurring_enabled():
    return (
        _operator_enabled()
        and config.has_section("brainstem_recurring_insights")
        and config["brainstem_recurring_insights"].getboolean(
            "enabled", fallback=False
        )
    )


def _data_actions_enabled():
    return (
        _operator_enabled()
        and os.environ.get("BRAINSTEM_STUDY_REAL_DATA_ACTIONS_ENABLED") == "true"
        and not config["brainstem_generic_studies"].getboolean(
            "generated_only", fallback=True
        )
    )


def _require_operator_enabled():
    if not _operator_enabled():
        raise StudyActivationError("study_operator_operations_disabled", 503)


def _operator_settings():
    section = config["brainstem_generic_studies"]
    return {
        "allowed_operators": [
            item.strip()
            for item in section.get("operator_wallets", "").split(",")
            if item.strip()
        ],
        "allowed_origins": [
            item.strip()
            for item in section.get("operator_allowed_origins", "").split(",")
            if item.strip()
        ],
        "chain_id": section.getint("operator_chain_id", fallback=11155420),
        "challenge_ttl": section.getint(
            "operator_challenge_ttl_seconds", fallback=300
        ),
    }


def _activation_service():
    _require_operator_enabled()
    return StudyActivationService(
        study_activation_dao,
        study_proposal_dao,
        DEFAULT_STUDY_REGISTRY,
        **_operator_settings(),
    )


def _operations_service():
    _require_operator_enabled()
    return StudyOperationsService(
        study_operations_dao,
        _activation_service(),
        DEFAULT_STUDY_REGISTRY,
        **_operator_settings(),
    )


def _data_authorization_service():
    if not _data_actions_enabled():
        raise StudyDataAuthorizationError("study_data_actions_disabled", 503)
    return StudyDataAuthorizationService(
        study_activation_dao,
        _activation_service(),
        manifest_sha256=os.environ.get("BRAINSTEM_STUDY_REVIEW_MANIFEST_SHA256", ""),
        cohort_release_id=os.environ.get(
            "BRAINSTEM_STUDY_ELIGIBILITY_RELEASE_ID", ""
        ),
        release_sha256=os.environ.get("BRAINSTEM_STUDY_RELEASE_SHA256", ""),
        algorithm_image_digest=os.environ.get(
            "BRAINSTEM_STUDY_RESULT_ALGORITHM_DIGEST", ""
        ),
        **_operator_settings(),
    )


def _generic_service():
    _require_participant_enabled()
    section = config["brainstem_generic_studies"]
    return GenericStudyService(
        participant_auth_service(),
        study_dao,
        pending_answers=pending_answer_store,
        operations=_operations_service() if _operator_enabled() else None,
        participant_binding_secret=section.get("participant_binding_secret"),
        participant_binding_key_id=section.get("participant_binding_key_id"),
        offering_access=_participant_offering_access,
        available_offerings=(
            None if _enabled() else {APDET_DIAGNOSIS_QUESTIONNAIRE_ID}
        ),
    )


def _participant_offering_access(offering_id, user):
    if offering_id != APDET_DIAGNOSIS_QUESTIONNAIRE_ID:
        return True
    release_id = os.environ.get("BRAINSTEM_STUDY_ELIGIBILITY_RELEASE_ID", "")
    consent_version = (
        config["brainstem_c2d"].get("consent_version", "")
        if config.has_section("brainstem_c2d")
        else ""
    )
    if not re.fullmatch(r"[0-9a-f]{64}", release_id) or not has_brainstem_data_consent(
        user
    ):
        return False
    try:
        members = CohortReleaseService(
            cohort_release_dao,
            user_dao,
            consent_version,
            purpose=FULL_NIGHT_COMPATIBILITY_POLICY.dataset_policy,
        ).active_member_ids(release_id)
    except CohortReleaseError:
        return False
    return user.get("_id") in members


def _study_recurring_service():
    if not _recurring_enabled():
        raise StudyRecurringError("study_recurring_disabled", 503)
    operations = _operations_service()
    enrollment = _generic_service()
    return StudyRecurringService(
        participant_auth_service(),
        user_dao,
        study_dao,
        enrollment,
        operations,
        DEFAULT_STUDY_REGISTRY,
        feature_enabled=True,
    )


def _full_night_selector():
    upload_root = Path(config["application"].get("upload_folder", "data"))
    if not upload_root.is_absolute():
        upload_root = Path.cwd() / upload_root
    consent_version = (
        config["brainstem_c2d"].get("consent_version", "")
        if config.has_section("brainstem_c2d")
        else ""
    )
    return BrainstemC2DExporter(
        image_metadata_dao,
        user_dao,
        image_metadata_dao,
        cohort_release_dao,
        upload_root,
        "",
        "preview",
        consent_version,
        policy=FULL_NIGHT_COMPATIBILITY_POLICY,
    )


def _eligibility_preview_service():
    if os.environ.get("BRAINSTEM_STUDY_ELIGIBILITY_PREVIEW_ENABLED") != "true":
        raise GenericStudyServiceError("study_eligibility_preview_disabled", 503)
    release_version = os.environ.get("BRAINSTEM_STUDY_RELEASE_VERSION", "")
    release_sha256 = os.environ.get("BRAINSTEM_STUDY_RELEASE_SHA256", "")
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", release_version) or not re.fullmatch(
        r"[0-9a-f]{64}", release_sha256
    ):
        raise GenericStudyServiceError("study_release_configuration_invalid", 503)
    return StudyEligibilityPreview(
        study_proposal_workflow,
        _full_night_selector(),
        os.environ.get("BRAINSTEM_STUDY_ELIGIBILITY_RELEASE_ID", ""),
        "brainstem.apdet-retrospective-study",
        release_version,
        release_sha256,
        generated_only=True,
    )


def _study_result_service():
    if os.environ.get("BRAINSTEM_STUDY_RESULTS_ENABLED") != "true":
        raise StudyResultError("study_results_disabled", 503)
    digest = os.environ.get("BRAINSTEM_STUDY_RESULT_ALGORITHM_DIGEST", "")
    release_id = os.environ.get("BRAINSTEM_STUDY_ELIGIBILITY_RELEASE_ID", "")
    release_version = os.environ.get("BRAINSTEM_STUDY_RELEASE_VERSION", "")
    release_sha256 = os.environ.get("BRAINSTEM_STUDY_RELEASE_SHA256", "")
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", digest) or not re.fullmatch(
        r"[0-9a-f]{64}", release_id
    ) or not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", release_version) or not re.fullmatch(
        r"[0-9a-f]{64}", release_sha256
    ):
        raise StudyResultError("study_results_configuration_invalid", 503)
    return StudyResultService(
        study_proposal_workflow,
        study_result_dao,
        image_metadata_dao,
        _full_night_selector(),
        release_id,
        digest,
        release_version,
        release_sha256,
    )


def _verified_metric_enrollment(user_id, offering_id, state):
    try:
        user = user_dao.get_doc_by_id(user_id)
        return _generic_service().load_verified_enrollment(
            user_id,
            offering_id,
            state=state,
            user=user,
        )
    except GenericStudyServiceError as error:
        if error.status_code >= 500:
            raise
        return None


study_operations_metrics = StudyOperationsMetricsSource(
    study_dao, _verified_metric_enrollment
)


def _token():
    authorization = request.headers.get("Authorization", "")
    if not authorization.startswith("Participant "):
        raise GenericStudyServiceError("participant_session_required", 401)
    return authorization[len("Participant ") :]


def _origin():
    return request.headers.get("X-Brainstem-Origin")


def _operator_origin():
    actual = request.headers.get("Origin")
    display = request.headers.get("X-Brainstem-Origin")
    if not actual or (display is not None and display.rstrip("/") != actual.rstrip("/")):
        raise StudyActivationError("study_operator_origin_forbidden", 403)
    return actual


def _json_body(max_bytes=MAX_BODY_BYTES):
    if not request.is_json:
        raise GenericStudyServiceError("json_required")
    if request.content_length is not None and request.content_length > max_bytes:
        raise GenericStudyServiceError("request_too_large", 413)
    raw = request.stream.read(max_bytes + 1)
    if len(raw) > max_bytes:
        raise GenericStudyServiceError("request_too_large", 413)
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise GenericStudyServiceError("json_invalid")
    if not isinstance(value, dict):
        raise GenericStudyServiceError("json_object_required")
    return value


def _proposal_body():
    try:
        return _json_body()
    except GenericStudyServiceError as error:
        if error.status_code == 413:
            raise StudyProposalPayloadTooLarge("Request body is too large") from error
        raise StudyProposalError(str(error)) from error


def _operation_body():
    try:
        return _json_body()
    except GenericStudyServiceError as error:
        raise StudyOperationsError("study_operation_request_invalid") from error


def _roles():
    value = get_jwt().get("roles", [])
    return set(value) if isinstance(value, list) else set()


def _can_review():
    roles = _roles()
    return "admin" in roles or any(
        "study_reviewer_{}".format(domain) in roles
        for domain in ("scientific", "privacy", "security", "ethics")
    )


def _can_review_domain(domain):
    roles = _roles()
    return "admin" in roles or "study_reviewer_{}".format(domain) in roles


def _can_operate():
    return "study_operator" in _roles()


def _can_research():
    return "study_researcher" in _roles()


def _no_store(response):
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["Pragma"] = "no-cache"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


@generic_study_routes.after_request
def generic_study_headers(response):
    return _no_store(response)


@generic_study_routes.errorhandler(GenericStudyServiceError)
def handle_study_error(error):
    message = (
        "Study service unavailable"
        if error.status_code >= 500
        else "Study request rejected"
    )
    return jsonify({"status": "failed", "message": message}), error.status_code


@generic_study_routes.errorhandler(ParticipantAuthError)
def handle_participant_auth_error(error):
    message = (
        "Study service unavailable"
        if error.status_code >= 500
        else "Study request rejected"
    )
    return jsonify({"status": "failed", "message": message}), error.status_code


@generic_study_routes.errorhandler(StudyRegistryError)
def handle_registry_error(_error):
    return jsonify({"status": "failed", "message": "Study request rejected"}), 404


@generic_study_routes.errorhandler(StudyProposalError)
def handle_proposal_error(error):
    return jsonify({"status": "failed", "message": error.message}), error.status_code


@generic_study_routes.errorhandler(StudyActivationError)
def handle_activation_error(error):
    message = (
        "Study service unavailable"
        if error.status_code >= 500
        else "Study activation request rejected"
    )
    return jsonify({"status": "failed", "message": message}), error.status_code


@generic_study_routes.errorhandler(StudyOperationsError)
def handle_operations_error(error):
    message = (
        "Study service unavailable"
        if error.status_code >= 500
        else "Study operation request rejected"
    )
    return jsonify({"status": "failed", "message": message}), error.status_code


@generic_study_routes.errorhandler(StudyDataAuthorizationError)
def handle_data_authorization_error(error):
    message = (
        "Study service unavailable"
        if error.status_code >= 500
        else "Study data request rejected"
    )
    return jsonify({"status": "failed", "message": message}), error.status_code


@generic_study_routes.errorhandler(StudyRecurringError)
def handle_study_recurring_error(error):
    message = (
        "Study recurring service unavailable"
        if error.status_code >= 500
        else "Study recurring request rejected"
    )
    return jsonify({"status": "failed", "message": message}), error.status_code


@generic_study_routes.errorhandler(StudyResultError)
def handle_study_result_error(error):
    message = (
        "Study result service unavailable"
        if error.status_code >= 500
        else "Study result rejected"
    )
    return jsonify({"status": "failed", "message": message}), error.status_code


@generic_study_routes.errorhandler(DBResultError)
def handle_database_error(_error):
    return jsonify({"status": "failed", "message": "Study service unavailable"}), 503


@generic_study_routes.route("/api/v1/studies/catalogue", methods=["GET"])
def study_catalogue():
    _require_participant_enabled()
    available = None if _enabled() else {APDET_DIAGNOSIS_QUESTIONNAIRE_ID}
    return jsonify(
        {
            "result": GenericStudyService(
                None, study_dao, available_offerings=available
            ).catalogue()
        }
    ), 200


@generic_study_routes.route(
    "/api/v1/participant-auth/studies/inbox", methods=["GET"]
)
def participant_study_inbox():
    result = _generic_service().inbox(_token(), _origin())
    return jsonify({"result": result}), 200


@generic_study_routes.route(
    "/api/v1/participant-auth/studies/<string:offering_id>/status",
    methods=["GET"],
)
def participant_study_offering_status(offering_id):
    result = _generic_service().status(_token(), _origin(), offering_id)
    return jsonify({"result": result}), 200


@generic_study_routes.route(
    "/api/v1/participant-auth/studies/<string:offering_id>/tasks",
    methods=["GET"],
)
def participant_study_tasks(offering_id):
    if request.args:
        raise GenericStudyServiceError("study_task_request_invalid")
    result = _generic_service().tasks(_token(), _origin(), offering_id)
    return jsonify({"result": result}), 200


@generic_study_routes.route(
    "/api/v1/participant-auth/studies/<string:offering_id>/recurring",
    methods=["GET"],
)
def participant_study_recurring_status(offering_id):
    if request.args:
        raise StudyRecurringError("study_recurring_request_invalid")
    result = _study_recurring_service().status(
        _token(), _origin(), offering_id
    )
    return jsonify({"result": result}), 200


@generic_study_routes.route(
    "/api/v1/participant-auth/studies/<string:offering_id>/recurring/challenges",
    methods=["POST"],
)
def participant_study_recurring_challenge(offering_id):
    body = _json_body()
    action = body.get("action")
    expected = {"action", "settings"} if action == "activate" else {"action"}
    if set(body) != expected:
        raise StudyRecurringError("study_recurring_request_invalid")
    result = _study_recurring_service().challenge(
        _token(),
        _origin(),
        offering_id,
        action,
        body.get("settings"),
    )
    return jsonify({"result": result}), 201


@generic_study_routes.route(
    "/api/v1/participant-auth/studies/<string:offering_id>/recurring/actions",
    methods=["POST"],
)
def participant_study_recurring_action(offering_id):
    body = _json_body()
    if set(body) != {"challengeId", "signature"}:
        raise StudyRecurringError("study_recurring_request_invalid")
    result = _study_recurring_service().apply(
        _token(),
        _origin(),
        offering_id,
        body["challengeId"],
        body["signature"],
    )
    return jsonify({"result": result}), 201


@generic_study_routes.route(
    "/api/v1/participant-auth/studies/<string:offering_id>/recurring/outbox",
    methods=["GET"],
)
def participant_study_recurring_outbox(offering_id):
    if request.args:
        raise StudyRecurringError("study_recurring_request_invalid")
    result = _study_recurring_service().list_outbox(
        _token(), _origin(), offering_id
    )
    return jsonify({"result": result}), 200


@generic_study_routes.route(
    "/api/v1/participant-auth/studies/<string:offering_id>/recurring/outbox/"
    "<string:notification_id>/read",
    methods=["POST"],
)
def participant_study_recurring_outbox_read(offering_id, notification_id):
    if _json_body():
        raise StudyRecurringError("study_recurring_request_invalid")
    result = _study_recurring_service().acknowledge(
        _token(), _origin(), offering_id, notification_id
    )
    return jsonify({"result": result}), 200


@generic_study_routes.route(
    "/api/v1/participant-auth/studies/<string:offering_id>/recurring/outbox/"
    "<string:notification_id>",
    methods=["DELETE"],
)
def participant_study_recurring_outbox_delete(offering_id, notification_id):
    if request.content_length not in (None, 0):
        raise StudyRecurringError("study_recurring_request_invalid")
    _study_recurring_service().delete_notification(
        _token(), _origin(), offering_id, notification_id
    )
    return "", 204


@generic_study_routes.route(
    "/api/v1/participant-auth/studies/<string:offering_id>/challenges",
    methods=["POST"],
)
def participant_study_offering_challenge(offering_id):
    body = _json_body()
    action = body.get("action")
    expected = (
        {"action", "releaseSha256", "surveyVersion", "answers"}
        if action == "answer"
        else {"action", "releaseSha256"}
    )
    if set(body) != expected:
        raise GenericStudyServiceError("study_action_invalid")
    answer = (
        {
            "releaseSha256": body["releaseSha256"],
            "surveyVersion": body["surveyVersion"],
            "answers": body["answers"],
        }
        if action == "answer"
        else None
    )
    result = _generic_service().challenge(
        _token(),
        _origin(),
        offering_id,
        action,
        answer,
        body["releaseSha256"],
    )
    return jsonify({"result": result}), 201


@generic_study_routes.route(
    "/api/v1/participant-auth/studies/<string:offering_id>/actions",
    methods=["POST"],
)
def participant_study_offering_action(offering_id):
    body = _json_body()
    if set(body) != {"challengeId", "signature"}:
        raise GenericStudyServiceError("study_action_invalid")
    result = _generic_service().apply(
        _token(),
        _origin(),
        offering_id,
        body["challengeId"],
        body["signature"],
    )
    return jsonify({"result": result}), 201


@generic_study_routes.route("/api/v1/study-proposals", methods=["POST"])
@jwt_required()
def create_study_proposal():
    _require_enabled()
    if not _can_research():
        raise StudyProposalForbidden("Study researcher role required")
    result = study_proposal_workflow.create(get_jwt_identity(), _proposal_body())
    return jsonify({"result": result}), 201


@generic_study_routes.route("/api/v1/study-proposals", methods=["GET"])
@jwt_required()
def list_my_study_proposals():
    _require_enabled()
    page, per_page = parse_page(
        request.args.get("page", "0"), request.args.get("per_page", "20")
    )
    result = study_proposal_workflow.list_accessible(
        get_jwt_identity(), page, per_page
    )
    return jsonify({"result": result}), 200


@generic_study_routes.route(
    "/api/v1/study-proposals/<string:proposal_id>", methods=["GET"]
)
@jwt_required()
def get_study_proposal(proposal_id):
    _require_enabled()
    result = study_proposal_workflow.get(proposal_id, get_jwt_identity())
    return jsonify({"result": result}), 200


@generic_study_routes.route(
    "/api/v1/study-proposals/<string:proposal_id>/eligibility-preview",
    methods=["GET"],
)
@jwt_required()
def study_eligibility_preview(proposal_id):
    _require_enabled()
    if set(request.args) != {"revisionId", "revisionSha256"}:
        raise StudyProposalError("Invalid eligibility preview request")
    result = _eligibility_preview_service().evaluate(
        proposal_id,
        get_jwt_identity(),
        request.args["revisionId"],
        request.args["revisionSha256"],
    )
    return jsonify({"result": result}), 200


@generic_study_routes.route(
    "/api/v1/study-proposals/<string:proposal_id>/results", methods=["GET"]
)
@jwt_required()
def list_study_results(proposal_id):
    _require_enabled()
    if request.args:
        raise StudyResultError("study_result_request_invalid")
    result = _study_result_service().list(proposal_id, get_jwt_identity())
    return jsonify({"result": result}), 200


@generic_study_routes.route(
    "/api/v1/study-proposals/<string:proposal_id>/results/status",
    methods=["GET"],
)
@jwt_required()
def study_result_status(proposal_id):
    _require_enabled()
    if request.args:
        raise StudyResultError("study_result_request_invalid")
    result = _study_result_service().status(proposal_id, get_jwt_identity())
    return jsonify({"result": result}), 200


@generic_study_routes.route(
    "/api/v1/internal/study-proposals/<string:proposal_id>/results",
    methods=["POST"],
)
def append_study_result(proposal_id):
    _require_enabled()
    token = os.environ.get("BRAINSTEM_STUDY_RESULT_NODE_TOKEN", "")
    if len(token) < 32 or not hmac.compare_digest(
        request.headers.get("Authorization", ""), "Bearer {}".format(token)
    ):
        raise StudyResultError("study_result_unauthorized", 401)
    result = _study_result_service().append(
        proposal_id, _json_body(MAX_STUDY_RESULT_BODY_BYTES)
    )
    return jsonify({"result": result}), 201


@generic_study_routes.route(
    "/api/v1/study-proposals/<string:proposal_id>/revisions", methods=["POST"]
)
@jwt_required()
def revise_study_proposal(proposal_id):
    _require_enabled()
    body = _proposal_body()
    expected = body.pop("expectedRevisionId", None)
    expected_sha256 = body.pop("expectedRevisionSha256", None)
    result = study_proposal_workflow.add_revision(
        proposal_id, get_jwt_identity(), body, expected, expected_sha256
    )
    return jsonify({"result": result}), 201


@generic_study_routes.route(
    "/api/v1/study-proposals/<string:proposal_id>/collaborators/<string:actor_id>",
    methods=["PUT", "DELETE"],
)
@jwt_required()
def manage_study_collaborator(proposal_id, actor_id):
    _require_enabled()
    body = _proposal_body()
    expected_fields = (
        {"role", "expectedAccessVersion"}
        if request.method == "PUT"
        else {"expectedAccessVersion"}
    )
    if set(body) != expected_fields:
        raise StudyProposalError("Invalid study collaborator fields")
    result = study_proposal_workflow.set_collaborator(
        proposal_id,
        get_jwt_identity(),
        actor_id,
        body.get("role"),
        body["expectedAccessVersion"],
    )
    return jsonify({"result": result}), 200


@generic_study_routes.route(
    "/api/v1/study-proposals/<string:proposal_id>/submit", methods=["POST"]
)
@jwt_required()
def submit_study_proposal(proposal_id):
    _require_enabled()
    body = _proposal_body()
    if set(body) != {"expectedRevisionId", "expectedRevisionSha256"}:
        raise StudyProposalError("Invalid submission fields")
    result = study_proposal_workflow.submit(
        proposal_id,
        get_jwt_identity(),
        body["expectedRevisionId"],
        body["expectedRevisionSha256"],
    )
    return jsonify({"result": result}), 201


@generic_study_routes.route("/api/v1/admin/study-proposals", methods=["GET"])
@jwt_required()
def list_study_proposal_queue():
    _require_enabled()
    if not _can_review():
        raise StudyProposalForbidden("Study reviewer role required")
    page, per_page = parse_page(
        request.args.get("page", "0"), request.args.get("per_page", "20")
    )
    result = study_proposal_workflow.list_queue(
        page, per_page, request.args.get("status")
    )
    return jsonify({"result": result}), 200


@generic_study_routes.route(
    "/api/v1/admin/study-proposals/<string:proposal_id>", methods=["GET"]
)
@jwt_required()
def get_study_proposal_for_review(proposal_id):
    _require_enabled()
    if not _can_review():
        raise StudyProposalForbidden("Study reviewer role required")
    result = study_proposal_workflow.get(
        proposal_id, get_jwt_identity(), can_review=True
    )
    if result.get("status") not in QUEUE_STATES - {"draft"}:
        raise StudyProposalNotFound("Study proposal not found")
    return jsonify({"result": result}), 200


@generic_study_routes.route(
    "/api/v1/admin/study-proposals/<string:proposal_id>/reviews",
    methods=["POST"],
)
@jwt_required()
def review_study_proposal(proposal_id):
    _require_enabled()
    body = _proposal_body()
    if set(body) != {
        "domain",
        "decision",
        "expectedRevisionId",
        "expectedRevisionSha256",
        "note",
        "evidenceSha256",
    }:
        raise StudyProposalError("Invalid study review fields")
    if not _can_review_domain(body["domain"]):
        raise StudyProposalForbidden("Study review domain role required")
    result = study_proposal_workflow.review(
        proposal_id,
        get_jwt_identity(),
        body["domain"],
        body["decision"],
        body["expectedRevisionId"],
        body["expectedRevisionSha256"],
        body["note"],
        body["evidenceSha256"],
    )
    return jsonify({"result": result}), 201


@generic_study_routes.route(
    "/api/v1/admin/study-proposals/<string:proposal_id>/activation/challenges",
    methods=["POST"],
)
@jwt_required()
def create_study_activation_challenge(proposal_id):
    _require_operator_enabled()
    if not _can_operate():
        raise StudyActivationError("study_operator_role_required", 403)
    body = _proposal_body()
    if set(body) != {"expectedRevisionId", "expectedRevisionSha256"}:
        raise StudyActivationError("study_activation_challenge_invalid")
    result = _activation_service().create_challenge(
        proposal_id,
        get_jwt_identity(),
        _operator_origin(),
        body["expectedRevisionId"],
        body["expectedRevisionSha256"],
    )
    return jsonify({"result": result}), 201


@generic_study_routes.route(
    "/api/v1/admin/study-proposals/<string:proposal_id>/activation/permits",
    methods=["POST"],
)
@jwt_required()
def create_study_activation_permit(proposal_id):
    _require_operator_enabled()
    if not _can_operate():
        raise StudyActivationError("study_operator_role_required", 403)
    body = _proposal_body()
    if set(body) != {"challengeId", "signature"}:
        raise StudyActivationError("study_activation_permit_invalid")
    result = _activation_service().apply(
        proposal_id,
        get_jwt_identity(),
        _operator_origin(),
        body["challengeId"],
        body["signature"],
    )
    return jsonify({"result": result}), 201


@generic_study_routes.route(
    "/api/v1/admin/study-proposals/<string:proposal_id>/data-actions/challenges",
    methods=["POST"],
)
@jwt_required()
def create_study_data_action_challenge(proposal_id):
    if not _can_operate():
        raise StudyDataAuthorizationError("study_data_operator_role_required", 403)
    body = _operation_body()
    if set(body) != {
        "action",
        "activationPermitId",
        "eligibilityReceiptSha256",
    }:
        raise StudyDataAuthorizationError("study_data_action_request_invalid")
    result = _data_authorization_service().create_challenge(
        body["action"],
        proposal_id,
        body["activationPermitId"],
        get_jwt_identity(),
        _operator_origin(),
        body["eligibilityReceiptSha256"],
    )
    return jsonify({"result": result}), 201


@generic_study_routes.route(
    "/api/v1/admin/study-proposals/<string:proposal_id>/data-actions/permits",
    methods=["POST"],
)
@jwt_required()
def create_study_data_action_permit(proposal_id):
    if not _can_operate():
        raise StudyDataAuthorizationError("study_data_operator_role_required", 403)
    body = _operation_body()
    if set(body) != {"challengeId", "signature"}:
        raise StudyDataAuthorizationError("study_data_action_request_invalid")
    result = _data_authorization_service().apply(
        proposal_id,
        get_jwt_identity(),
        _operator_origin(),
        body["challengeId"],
        body["signature"],
    )
    return jsonify({"result": result}), 201


@generic_study_routes.route(
    "/api/v1/admin/study-proposals/<string:proposal_id>/data-actions/eligibility",
    methods=["POST"],
)
@jwt_required()
def run_study_data_eligibility(proposal_id):
    if not _can_operate():
        raise StudyDataAuthorizationError("study_data_operator_role_required", 403)
    body = _operation_body()
    if set(body) != {"permitId"}:
        raise StudyDataAuthorizationError("study_data_action_request_invalid")
    service = _data_authorization_service()

    def evaluate(binding):
        return StudyEligibilityPreview(
            study_proposal_workflow,
            _full_night_selector(),
            binding["cohortReleaseId"],
            binding["offeringId"],
            binding["releaseVersion"],
            binding["releaseSha256"],
        ).evaluate(
            proposal_id,
            get_jwt_identity(),
            binding["revisionId"],
            binding["revisionSha256"],
            authorized=True,
        )

    result, receipt = service.execute(
        proposal_id,
        body["permitId"],
        "eligibility",
        body["permitId"],
        evaluate,
    )
    return jsonify(
        {"result": {**result, "authorizationReceiptSha256": receipt["receiptSha256"]}}
    ), 200


@generic_study_routes.route(
    "/api/v1/admin/study-proposals/<string:proposal_id>/operations",
    methods=["GET"],
)
@jwt_required()
def get_study_operations(proposal_id):
    _require_operator_enabled()
    if not _can_operate():
        raise StudyOperationsError("study_operator_role_required", 403)
    if set(request.args) != {"permitId"}:
        raise StudyOperationsError("study_operation_request_invalid")
    result = _operations_service().status(proposal_id, request.args["permitId"])
    return jsonify({"result": result}), 200


@generic_study_routes.route(
    "/api/v1/researcher/study-proposals/<string:proposal_id>/operations",
    methods=["GET"],
)
@jwt_required()
def get_researcher_study_operations(proposal_id):
    _require_operator_enabled()
    if not _can_research():
        raise StudyOperationsError("study_researcher_role_required", 403)
    if set(request.args) != {"permitId"}:
        raise StudyOperationsError("study_operation_request_invalid")
    result = _operations_service().researcher_projection(
        proposal_id,
        request.args["permitId"],
        study_operations_metrics,
    )
    return jsonify({"result": result}), 200


@generic_study_routes.route(
    "/api/v1/admin/study-proposals/<string:proposal_id>/operations/challenges",
    methods=["POST"],
)
@jwt_required()
def create_study_operation_challenge(proposal_id):
    _require_operator_enabled()
    if not _can_operate():
        raise StudyOperationsError("study_operator_role_required", 403)
    body = _operation_body()
    if set(body) != {
        "permitId",
        "action",
        "expectedStateSha256",
        "idempotencyKey",
        "details",
    }:
        raise StudyOperationsError("study_operation_request_invalid")
    result = _operations_service().create_challenge(
        proposal_id,
        get_jwt_identity(),
        _operator_origin(),
        body["permitId"],
        body["action"],
        body["expectedStateSha256"],
        body["idempotencyKey"],
        body["details"],
    )
    return jsonify({"result": result}), 201


@generic_study_routes.route(
    "/api/v1/admin/study-proposals/<string:proposal_id>/operations/transitions",
    methods=["POST"],
)
@jwt_required()
def apply_study_operation(proposal_id):
    _require_operator_enabled()
    if not _can_operate():
        raise StudyOperationsError("study_operator_role_required", 403)
    body = _operation_body()
    if set(body) != {"challengeId", "signature"}:
        raise StudyOperationsError("study_operation_request_invalid")
    result = _operations_service().apply(
        proposal_id,
        get_jwt_identity(),
        _operator_origin(),
        body["challengeId"],
        body["signature"],
    )
    return jsonify({"result": result}), 201
