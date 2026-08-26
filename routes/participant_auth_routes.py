import hmac
import json
from pathlib import Path

from flask import Blueprint, Response, jsonify, request

from commands.dataunions.brainstem.personal_insight import (
    BrainstemPersonalInsightService,
    LEGACY_POLICY,
    MAX_HISTORY_ENTRIES,
    PersonalInsightError,
    personal_insight_policy,
)
from commands.dataunions.brainstem.cohort_reference import CohortReferenceService
from commands.dataunions.brainstem.cohort_release import CohortReleaseService
from commands.dataunions.brainstem.study_service import (
    BrainstemStudyService,
    StudyServiceError,
)
from commands.users.participant_auth import ParticipantAuthError, ParticipantAuthService
from config import config
from dao.base_dao import DBResultError
from dao.cohort_release_dao import cohort_release_dao
from dao.metadata_dao import image_metadata_dao
from dao.personal_insight_dao import personal_insight_dao
from dao.sessions_dao import sessions_dao
from dao.study_dao import study_dao
from dao.users_dao import user_dao
from security.http_policy import parse_allowed_origins


MAX_BODY_BYTES = 8 * 1024
participant_auth_routes = Blueprint("participant_auth_routes", __name__)


def _settings():
    if not config.has_section("participant_auth"):
        return None
    allowed_origins = parse_allowed_origins(
        config["participant_auth"].get("allowed_origins", "")
    )
    if not config["participant_auth"].getboolean("enabled", fallback=False):
        allowed_origins = []
    return {
        "allowed_origins": allowed_origins,
        "chain_id": config["participant_auth"].getint(
            "chain_id", fallback=11155420
        ),
        "challenge_ttl": config["participant_auth"].getint(
            "challenge_ttl_seconds", fallback=300
        ),
        "session_ttl": config["participant_auth"].getint(
            "session_ttl_seconds", fallback=900
        ),
    }


def _service():
    settings = _settings()
    if not settings:
        raise ParticipantAuthError("Participant authentication is disabled", 503)
    return ParticipantAuthService(sessions_dao, user_dao, **settings)


def _personal_service(analysis=LEGACY_POLICY.analysis_id):
    if (
        not config.has_section("brainstem_personal_insight")
        or not config["brainstem_personal_insight"].getboolean(
            "enabled", fallback=False
        )
    ):
        raise PersonalInsightError("personal_insight_disabled", 503)
    upload_root = Path(config["application"].get("upload_folder", "data"))
    if not upload_root.is_absolute():
        upload_root = Path.cwd() / upload_root
    settings = _settings()
    if not settings:
        raise PersonalInsightError("personal_insight_disabled", 503)
    section = config["brainstem_personal_insight"]
    prefix = (
        "sleep_baseline"
        if analysis in {"sleep-baseline", "brainstem.sleep-baseline/v1"}
        else "resting_sample_entropy"
        if analysis in {
            "resting-rr-sample-entropy",
            "brainstem.resting-rr-sample-entropy/v1",
        }
        else "resting_hrv_methods"
    )
    policy = personal_insight_policy(
        analysis,
        approved_manifest_sha256=section.get(
            "{}_approved_manifest_sha256".format(prefix), ""
        ).strip(),
        reference_sha256=section.get(
            "{}_reference_sha256".format(prefix), ""
        ).strip(),
    )
    image_setting = (
        "algorithm_image_digest"
        if policy == LEGACY_POLICY
        else "{}_algorithm_image_digest".format(prefix)
    )
    reference_state = None
    if policy.reference_sha256 is not None:
        c2d = config["brainstem_c2d"]
        release_service = CohortReleaseService(
            release_dao=cohort_release_dao,
            users_dao=user_dao,
            consent_version=c2d.get("consent_version", "").strip(),
            metadata_dao=image_metadata_dao,
            refresh_min_contributors=c2d.getint(
                "refresh_min_contributors", fallback=20
            ),
        )
        reference_state = CohortReferenceService(
            cohort_release_dao, release_service
        ).bound_state
    return BrainstemPersonalInsightService(
        auth_service=_service(),
        personal_dao=personal_insight_dao,
        metadata_dao=image_metadata_dao,
        users_dao=user_dao,
        upload_root=upload_root,
        algorithm_image_digest=section.get(image_setting, "").strip(),
        policy=policy,
        chain_id=settings["chain_id"],
        challenge_ttl=config["brainstem_personal_insight"].getint(
            "challenge_ttl_seconds", fallback=300
        ),
        grant_ttl=config["brainstem_personal_insight"].getint(
            "grant_ttl_seconds", fallback=300
        ),
        capability_ttl=config["brainstem_personal_insight"].getint(
            "capability_ttl_seconds", fallback=60
        ),
        result_ttl=config["brainstem_personal_insight"].getint(
            "result_ttl_seconds", fallback=1209600
        ),
        reference_state=reference_state,
    )


def _study_service(participant_auth=True):
    if (
        not config.has_section("brainstem_studies")
        or not config["brainstem_studies"].getboolean(
            "enabled", fallback=False
        )
    ):
        raise StudyServiceError("study_disabled", 503)
    return BrainstemStudyService(
        _service() if participant_auth else None, study_dao
    )


def _json_body():
    if not request.is_json:
        raise ParticipantAuthError("Content-Type must be application/json")
    if request.content_length is not None and request.content_length > MAX_BODY_BYTES:
        raise ParticipantAuthError("Request body is too large", 413)
    raw = request.stream.read(MAX_BODY_BYTES + 1)
    if len(raw) > MAX_BODY_BYTES:
        raise ParticipantAuthError("Request body is too large", 413)
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise ParticipantAuthError("A valid JSON object is required")
    if not isinstance(value, dict):
        raise ParticipantAuthError("A JSON object is required")
    return value


def _origin():
    return request.headers.get("X-Brainstem-Origin")


def _token():
    authorization = request.headers.get("Authorization", "")
    if not authorization.startswith("Participant "):
        raise ParticipantAuthError("Participant session is required", 401)
    return authorization[len("Participant ") :]


def _no_store(response):
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["Pragma"] = "no-cache"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


@participant_auth_routes.after_request
def participant_auth_headers(response):
    return _no_store(response)


@participant_auth_routes.errorhandler(ParticipantAuthError)
def handle_participant_auth_error(error):
    return jsonify({"status": "failed", "message": error.message}), error.status_code


@participant_auth_routes.errorhandler(PersonalInsightError)
def handle_personal_insight_error(error):
    message = (
        "Personal Insight service unavailable"
        if error.status_code >= 500
        else "Personal Insight request rejected"
    )
    return jsonify({"status": "failed", "message": message}), error.status_code


@participant_auth_routes.errorhandler(StudyServiceError)
def handle_study_error(error):
    message = (
        "Study service unavailable"
        if error.status_code >= 500
        else "Study request rejected"
    )
    return jsonify({"status": "failed", "message": message}), error.status_code


@participant_auth_routes.errorhandler(DBResultError)
def handle_participant_auth_database_error(_error):
    return jsonify({"status": "failed", "message": "Participant service unavailable"}), 503


@participant_auth_routes.route(
    "/api/v1/participant-auth/challenges", methods=["POST"]
)
def create_participant_challenge():
    body = _json_body()
    return jsonify({"result": _service().create_challenge(body.get("address"), _origin())}), 201


@participant_auth_routes.route("/api/v1/participant-auth/sessions", methods=["POST"])
def create_participant_session():
    body = _json_body()
    result = _service().create_session(
        body.get("challengeId"),
        body.get("address"),
        body.get("signature"),
        _origin(),
    )
    return jsonify({"result": result}), 201


@participant_auth_routes.route(
    "/api/v1/participant-auth/self-status", methods=["GET"]
)
def participant_self_status():
    return jsonify({"result": _service().self_status(_token(), _origin())}), 200


@participant_auth_routes.route(
    "/api/v1/participant-auth/session", methods=["DELETE"]
)
def delete_participant_session():
    _service().logout(_token(), _origin())
    return "", 204


@participant_auth_routes.route(
    "/api/v1/participant-auth/studies/recording-feasibility/status",
    methods=["GET"],
)
def participant_study_status():
    return jsonify({"result": _study_service().status(_token(), _origin())}), 200


@participant_auth_routes.route(
    "/api/v1/studies/recording-feasibility/status",
    methods=["GET"],
)
def researcher_study_status():
    return jsonify({"result": _study_service(False).researcher_status()}), 200


@participant_auth_routes.route(
    "/api/v1/participant-auth/studies/recording-feasibility/survey",
    methods=["POST"],
)
def participant_study_survey():
    raise StudyServiceError("signed_survey_action_required", 409)


@participant_auth_routes.route(
    "/api/v1/participant-auth/studies/recording-feasibility/challenges",
    methods=["POST"],
)
def participant_study_challenge():
    body = _json_body()
    action = body.get("action")
    expected = (
        {"action", "surveyVersion", "answers"}
        if action == "survey"
        else {"action"}
    )
    if set(body) != expected:
        raise StudyServiceError("study_action_invalid")
    result = _study_service().challenge(
        _token(),
        _origin(),
        action,
        (
            {
                "surveyVersion": body["surveyVersion"],
                "answers": body["answers"],
            }
            if action == "survey"
            else None
        ),
    )
    return jsonify({"result": result}), 201


@participant_auth_routes.route(
    "/api/v1/participant-auth/studies/recording-feasibility/actions",
    methods=["POST"],
)
def participant_study_action():
    body = _json_body()
    expected = {"challengeId", "signature"}
    if "surveyVersion" in body or "answers" in body:
        expected |= {"surveyVersion", "answers"}
    if set(body) != expected:
        raise StudyServiceError("study_action_invalid")
    result = _study_service().apply(
        _token(),
        _origin(),
        body["challengeId"],
        body["signature"],
        (
            {
                "surveyVersion": body["surveyVersion"],
                "answers": body["answers"],
            }
            if "surveyVersion" in body
            else None
        ),
    )
    return jsonify({"result": result}), 201


@participant_auth_routes.route(
    "/api/v1/participant-auth/personal-insights/<analysis_slug>/challenges",
    methods=["POST"],
)
def create_personal_insight_challenge(analysis_slug):
    if _json_body():
        raise PersonalInsightError("challenge_request_invalid")
    result = _personal_service(analysis_slug).create_challenge(_token(), _origin())
    return jsonify({"result": result}), 201


@participant_auth_routes.route(
    "/api/v1/participant-auth/personal-insights/<analysis_slug>/grants",
    methods=["POST"],
)
def exchange_personal_insight_challenge(analysis_slug):
    body = _json_body()
    if set(body) != {"challengeId", "signature"}:
        raise PersonalInsightError("grant_request_invalid")
    result = _personal_service(analysis_slug).exchange(
        _token(),
        _origin(),
        body["challengeId"],
        body["signature"],
    )
    return jsonify({"result": result}), 201


@participant_auth_routes.route(
    "/api/v1/participant-auth/personal-insights/history",
    methods=["GET"],
)
@participant_auth_routes.route(
    "/api/v1/participant-auth/personal-insights/<analysis_slug>/history",
    methods=["GET"],
)
def list_personal_insight_history(analysis_slug=None):
    if set(request.args) - {"limit"}:
        raise PersonalInsightError("history_request_invalid")
    raw_limit = request.args.get("limit", "20")
    if (
        not raw_limit.isascii()
        or not raw_limit.isdigit()
        or not 1 <= int(raw_limit) <= MAX_HISTORY_ENTRIES
    ):
        raise PersonalInsightError("history_request_invalid")
    result = _personal_service(
        analysis_slug or LEGACY_POLICY.analysis_id
    ).history(
        _token(), _origin(), int(raw_limit)
    )
    return jsonify({"result": result}), 200


@participant_auth_routes.route(
    "/api/v1/participant-auth/personal-insights/history/<history_id>/access",
    methods=["POST"],
)
@participant_auth_routes.route(
    "/api/v1/participant-auth/personal-insights/<analysis_slug>/history/"
    "<history_id>/access",
    methods=["POST"],
)
def create_personal_insight_history_access(history_id, analysis_slug=None):
    body = _json_body()
    if set(body) != {"action"}:
        raise PersonalInsightError("access_request_invalid")
    result = _personal_service(
        analysis_slug or LEGACY_POLICY.analysis_id
    ).issue_history_access(
        _token(), _origin(), history_id, body["action"]
    )
    return jsonify({"result": result}), 201


def _node_authorized():
    if not config.has_section("brainstem_personal_insight"):
        return False
    token = config["brainstem_personal_insight"].get(
        "node_bearer_token", ""
    ).strip()
    authorization = request.headers.get("Authorization", "")
    return (
        len(token) >= 32
        and not token.startswith("<")
        and hmac.compare_digest(authorization, "Bearer {}".format(token))
    )


@participant_auth_routes.route(
    "/api/v1/internal/personal-insights/grants/claim", methods=["POST"]
)
def claim_personal_insight_grant():
    if not _node_authorized():
        return jsonify({"status": "failed", "message": "Unauthorized"}), 401
    body = _json_body()
    if set(body) != {"analysisId", "grant", "jobId", "runId"}:
        raise PersonalInsightError("claim_request_invalid")
    result = _personal_service(body["analysisId"]).claim(
        body["grant"], body["jobId"], body["runId"]
    )
    return jsonify({"result": result}), 200


@participant_auth_routes.route(
    "/api/v1/internal/personal-insights/dataset", methods=["GET"]
)
def fetch_personal_insight_dataset():
    if not _node_authorized():
        return jsonify({"status": "failed", "message": "Unauthorized"}), 401
    artifact = _personal_service(
        request.headers.get("X-Brainstem-Analysis-Id", "")
    ).fetch(
        request.headers.get("X-Brainstem-Personal-Grant", ""),
        request.headers.get("X-Ocean-Compute-Job-Id", ""),
    )
    response = Response(artifact.body, status=200, mimetype="application/json")
    response.headers["Content-Length"] = str(len(artifact.body))
    response.headers["X-Content-SHA256"] = artifact.checksum
    return response


@participant_auth_routes.route(
    "/api/v1/internal/personal-insights/runs/complete", methods=["POST"]
)
def complete_personal_insight_run():
    if not _node_authorized():
        return jsonify({"status": "failed", "message": "Unauthorized"}), 401
    body = _json_body()
    if set(body) != {
        "analysisId",
        "grant",
        "jobId",
        "runId",
        "resultSha256",
    }:
        raise PersonalInsightError("complete_request_invalid")
    result = _personal_service(body["analysisId"]).complete(
        body["grant"],
        body["jobId"],
        body["runId"],
        body["resultSha256"],
    )
    return jsonify({"result": result}), 200


@participant_auth_routes.route(
    "/api/v1/internal/personal-insights/runs/revalidate", methods=["POST"]
)
def revalidate_personal_insight_run():
    if not _node_authorized():
        return jsonify({"status": "failed", "message": "Unauthorized"}), 401
    body = _json_body()
    if set(body) != {"analysisId", "grant", "jobId", "runId"}:
        raise PersonalInsightError("revalidate_request_invalid")
    result = _personal_service(body["analysisId"]).revalidate(
        body["grant"], body["jobId"], body["runId"]
    )
    return jsonify({"result": result}), 200


@participant_auth_routes.route(
    "/api/v1/internal/personal-insights/history/revalidate", methods=["POST"]
)
def revalidate_personal_insight_history():
    if not _node_authorized():
        return jsonify({"status": "failed", "message": "Unauthorized"}), 401
    body = _json_body()
    if set(body) != {"analysisId", "historyId"}:
        raise PersonalInsightError("revalidate_request_invalid")
    result = _personal_service(body["analysisId"]).revalidate_history(
        body["historyId"]
    )
    return jsonify({"result": result}), 200


@participant_auth_routes.route(
    "/api/v1/participant-auth/personal-insights/runs/<run_id>/access",
    methods=["POST"],
)
def create_personal_insight_access(run_id):
    body = _json_body()
    if set(body) != {"analysisId", "grant", "action"}:
        raise PersonalInsightError("access_request_invalid")
    result = _personal_service(body["analysisId"]).issue_access(
        _token(),
        _origin(),
        body["grant"],
        run_id,
        body["action"],
    )
    return jsonify({"result": result}), 201


@participant_auth_routes.route(
    "/api/v1/internal/personal-insights/capabilities/consume",
    methods=["POST"],
)
def consume_personal_insight_access():
    if not _node_authorized():
        return jsonify({"status": "failed", "message": "Unauthorized"}), 401
    body = _json_body()
    if set(body) != {"analysisId", "capability", "runId", "action"}:
        raise PersonalInsightError("capability_request_invalid")
    result = _personal_service(body["analysisId"]).consume_access(
        body["capability"], body["runId"], body["action"]
    )
    return jsonify({"result": result}), 200


@participant_auth_routes.route(
    "/api/v1/internal/personal-insights/history/capabilities/consume",
    methods=["POST"],
)
def consume_personal_insight_history_access():
    if not _node_authorized():
        return jsonify({"status": "failed", "message": "Unauthorized"}), 401
    body = _json_body()
    if set(body) != {"analysisId", "capability", "historyId", "action"}:
        raise PersonalInsightError("capability_request_invalid")
    result = _personal_service(body["analysisId"]).consume_history_access(
        body["capability"], body["historyId"], body["action"]
    )
    return jsonify({"result": result}), 200
