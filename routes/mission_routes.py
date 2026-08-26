import json
from dao.users_dao import user_dao

from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity

from commands.missions.fetch_missions import FetchUserMissionsInformationCommand, GetMissionByIdCommand, FetchUserMissionsOverViewCommand
from commands.metadata.get_collector_storer_amount_by_mission_id import GetCollectorStorerAmountByMissionID
from models.missions import MissionStatus, MissionType
from dao.missions_dao import missions_dao
from dao.users_dao import user_dao

mission_routes = Blueprint("mission_routes", __name__)


@mission_routes.route("/info", methods=["GET"])
@jwt_required()
def get_all_user_missions_information():
    mission_statuses = request.args.getlist('status', type=MissionStatus)
    mission_types = request.args.getlist('type', type=MissionType)
    page = request.args.get('page', 1, type=int)
    bounty_id = request.args.get('bounty_id', type=str)
    sort_by = request.args.get('sort_by', type=str, default="created_at")
    sort_direction = request.args.get('sort_direction', type=str, default="desc")

    public_address = get_jwt_identity()

    fetch_mission_command = FetchUserMissionsInformationCommand(public_address, mission_types, mission_statuses, page,
                                                                sort_by=sort_by, sort_direction=sort_direction,
                                                                bounty_id=bounty_id)
    result = fetch_mission_command.execute()

    if not fetch_mission_command.successful:
        return (
            jsonify(
                {"status": "failed", "messages": fetch_mission_command.messages}
            ),
            400,
        )
    return jsonify(result), 200


@mission_routes.route("/", methods=["GET"])
@jwt_required()
def get_mission_information():
    mission_id = request.args.get('mission_id', type=str)
    public_address = get_jwt_identity()

    fetch_mission_command = GetMissionByIdCommand(public_address, mission_id)
    result = fetch_mission_command.execute()

    if not fetch_mission_command.successful:
        return (
            jsonify(
                {"status": "failed", "messages": fetch_mission_command.messages}
            ),
            400,
        )
    return jsonify(result), 200

@mission_routes.route("/get_amount_storer_collector/<string:mission_id>", methods=["GET"])
@jwt_required()
def get_amount_storer_collector(mission_id):
    fetch_metadata_command = GetCollectorStorerAmountByMissionID(mission_id)
    collector_storer_amount = fetch_metadata_command.execute()

    if not fetch_metadata_command.successful:
        return (
            jsonify(
                {"status": "failed", "messages": fetch_metadata_command.messages}
            ),
            400,
        )
    return jsonify({'status': 'success', 'result': collector_storer_amount})


@mission_routes.route("/get_all_missions_info/<string:creator_id>", methods=["GET"])
# @requires_user_role(UserRoleType.Creator)
def get_all_missions_info(creator_id):
    user = user_dao.get_doc_by_id(creator_id)
    if(len(user) == 0):
        return jsonify({
                'status': 'failed',
                'messages': "Invalid `creator_id`",
            }), 400
    public_address = user.get('public_address')
    
    missions = missions_dao.get_missions_by_public_address(public_address)
    missions_result = list()
    for doc in missions:
        fetch_metadata_command = GetCollectorStorerAmountByMissionID(doc["_id"])
        result = fetch_metadata_command.execute()
        if result:
            missions_result.append(result)
    return jsonify({'status': 'success', 'result': missions_result})

@mission_routes.route("/get_total_missions_info/<string:creator_id>", methods=["GET"])
# @requires_user_role(UserRoleType.Creator)
def get_total_missions_info(creator_id):
    user = user_dao.get_doc_by_id(creator_id)
    if(len(user) == 0):
        return jsonify({
                'status': 'failed',
                'messages': "Invalid `creator_id`",
            }), 400
    public_address = user.get('public_address')
    
    missions = missions_dao.get_missions_by_public_address(public_address)
    missions_result = list()
    collector_amount = 0
    storer_amount = 0
    collector_reward = 0
    for doc in missions:
        fetch_metadata_command = GetCollectorStorerAmountByMissionID(doc["_id"])
        result = fetch_metadata_command.execute()
        if result:
            collector_amount += result['collector_amount']
            storer_amount += result['storer_amount']
            collector_reward += result['collector_reward']
            missions_result.append(result)
    return jsonify({'status': 'success', 'collector_amount': collector_amount, 
    'storer_amount': storer_amount, 'collector_reward': collector_reward})

@mission_routes.route("/overview_info", methods=["GET"])
@jwt_required()
def get_all_user_missions_overview_information():
    mission_statuses = request.args.getlist('status', type=MissionStatus)
    mission_types = request.args.getlist('type', type=MissionType)
    page = request.args.get('page', 1, type=int)
    # public_address = request.args.get('public_address')
    bounty_id = request.args.get('bounty_id', type=str)
    sort_by = request.args.get('sort_by', type=str, default="created_at")
    sort_direction = request.args.get('sort_direction', type=str, default="desc")

    public_address = get_jwt_identity()

    fetch_mission_command = FetchUserMissionsOverViewCommand(public_address, mission_types, mission_statuses, page,
                                                                sort_by=sort_by, sort_direction=sort_direction,
                                                                bounty_id=bounty_id)
    result = fetch_mission_command.execute()

    if not fetch_mission_command.successful:
        return (
            jsonify(
                {"status": "failed", "messages": fetch_mission_command.messages}
            ),
            400,
        )
    return jsonify(result), 200
