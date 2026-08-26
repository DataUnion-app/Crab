import json

from flask import Blueprint, jsonify, request
from flask_jwt_extended import get_jwt, get_jwt_identity, jwt_required

from commands.dataunions.brainstem.algorithm_proposals import (
    AlgorithmProposalError,
    AlgorithmProposalWorkflow,
    ProposalPayloadTooLargeError,
    ProposalValidationError,
    parse_pagination,
)
from dao.algorithm_proposal_dao import algorithm_proposal_dao
from dao.base_dao import DBResultError


MAX_BODY_BYTES = 16 * 1024
algorithm_proposal_routes = Blueprint("algorithm_proposal_routes", __name__)
algorithm_proposal_workflow = AlgorithmProposalWorkflow(algorithm_proposal_dao)


def _is_admin():
    roles = get_jwt().get("roles", [])
    return isinstance(roles, list) and "admin" in roles


def _json_body():
    if not request.is_json:
        raise ProposalValidationError("Content-Type must be application/json")
    if request.content_length is not None and request.content_length > MAX_BODY_BYTES:
        raise ProposalPayloadTooLargeError("Request body is too large")
    raw = request.stream.read(MAX_BODY_BYTES + 1)
    if len(raw) > MAX_BODY_BYTES:
        raise ProposalPayloadTooLargeError("Request body is too large")
    try:
        payload = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise ProposalValidationError("A valid JSON object is required")
    if not isinstance(payload, dict):
        raise ProposalValidationError("A JSON object is required")
    return payload


def _pagination():
    return parse_pagination(
        request.args.get("page", "0"), request.args.get("per_page", "20")
    )


def _success(result, status=200):
    return jsonify({"result": result}), status


def _error_response(error):
    return jsonify({"status": "failed", "message": error.message}), error.status_code


@algorithm_proposal_routes.errorhandler(AlgorithmProposalError)
def handle_proposal_error(error):
    return _error_response(error)


@algorithm_proposal_routes.errorhandler(DBResultError)
def handle_database_error(_error):
    return (
        jsonify({"status": "failed", "message": "Proposal service unavailable"}),
        503,
    )


@algorithm_proposal_routes.route("/api/v1/algorithm-proposals", methods=["POST"])
@jwt_required()
def create_algorithm_proposal():
    proposal = algorithm_proposal_workflow.create(get_jwt_identity(), _json_body())
    return _success(proposal, 201)


@algorithm_proposal_routes.route("/api/v1/algorithm-proposals", methods=["GET"])
@jwt_required()
def list_my_algorithm_proposals():
    page, per_page = _pagination()
    result = algorithm_proposal_workflow.list_for_submitter(
        get_jwt_identity(), page, per_page
    )
    return _success(result)


@algorithm_proposal_routes.route(
    "/api/v1/algorithm-proposals/<string:proposal_id>", methods=["GET"]
)
@jwt_required()
def get_algorithm_proposal(proposal_id):
    result = algorithm_proposal_workflow.get_for_actor(
        proposal_id, get_jwt_identity(), is_admin=_is_admin()
    )
    return _success(result)


@algorithm_proposal_routes.route(
    "/api/v1/algorithm-proposals/<string:proposal_id>/revisions", methods=["POST"]
)
@jwt_required()
def add_algorithm_proposal_revision(proposal_id):
    payload = _json_body()
    expected_revision_id = payload.pop("expected_revision_id", None)
    result = algorithm_proposal_workflow.add_revision(
        proposal_id,
        get_jwt_identity(),
        payload,
        expected_revision_id,
    )
    return _success(result, 201)


@algorithm_proposal_routes.route("/api/v1/admin/algorithm-proposals", methods=["GET"])
@jwt_required()
def list_algorithm_proposal_queue():
    if not _is_admin():
        return jsonify({"status": "failed", "message": "Admin role required"}), 403
    page, per_page = _pagination()
    result = algorithm_proposal_workflow.list_for_admin(
        page, per_page, request.args.get("status")
    )
    return _success(result)


@algorithm_proposal_routes.route(
    "/api/v1/admin/algorithm-proposals/<string:proposal_id>/events",
    methods=["POST"],
)
@jwt_required()
def append_algorithm_proposal_event(proposal_id):
    if not _is_admin():
        return jsonify({"status": "failed", "message": "Admin role required"}), 403
    result = algorithm_proposal_workflow.append_admin_event(
        proposal_id, get_jwt_identity(), _json_body()
    )
    return _success(result)
