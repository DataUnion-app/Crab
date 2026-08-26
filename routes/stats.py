import datetime
import logging
import json

from flask import Blueprint, request, jsonify
from flask_jwt_extended import get_jwt_identity, jwt_required
import pandas as pd

from commands.handshake.handshake_commands import GetHandshakeList, GetHandShakesPerHour, GetHandShakesByTime
from commands.query_view_command_reduced import QueryViewCommandReduced
from commands.stats.entity_stats import GetEntityCountBySource, GetEntityUploadsPerHour, GetEntityAllEntities, \
    GetClassificationAccuracy
from commands.stats.overall_stats2_command import OverallStats2Command
from commands.stats.overall_stats_command import OverallStatsCommand
from commands.stats.success_rate import SuccessRate
from commands.stats.tag_stats_by_bounty import GetTagStatsByBountyCommand
from commands.stats.tags_stats_command import TagStatsCommand
from commands.stats.user_stats2_command import UserStats2Command
from commands.stats.user_stats_command import UserStatsCommand
from dao.metadata_dao import image_metadata_dao
from models.db_name import DatabaseName

stats_routes = Blueprint("stats_routes", __name__)


@stats_routes.route("/overall", methods=["GET"])
def get_overall_stats():
    args = request.args
    required_params = {"start_date", "end_date"}
    if not all(elem in args.keys() for elem in required_params):
        return (
            jsonify(
                {
                    "status": "failed",
                    "message": "Invalid input body. Expected query parameters :{0}".format(
                        required_params
                    ),
                }
            ),
            400,
        )
    try:
        entity_type = args.get("entity_type") or "image"
        overall_stats_c = OverallStatsCommand(entity_type)

        overall_stats_c.input = {
            "start_date": args.get("start_date"),
            "end_date": args.get("end_date"),
        }
        response = overall_stats_c.execute()
        if overall_stats_c.successful:
            return {"status": "success", "result": response}, 200
        else:
            return (
                jsonify({"status": "failed", "messages": overall_stats_c.messages}),
                400,
            )
    except ValueError:
        return (
            jsonify(
                {
                    "status": "failed",
                    "messages": ["Value error: Please check if input is correct"],
                }
            ),
            400,
        )
    except Exception as e:
        logging.error(e, exc_info=True)
        return (
            jsonify(
                {
                    "status": "failed",
                    "messages": ["Please contact support team."],
                }
            ),
            400,
        )


@stats_routes.route("/overall-tags", methods=["GET"])
def get_tag_stats():
    args = request.args

    entity_type = args.get("entity_type") or "image"

    get_tag_stats_command = TagStatsCommand(entity_type)
    get_tag_stats_command.input = {
        "start_date": args.get("start_date"),
        "end_date": args.get("end_date"),
    }
    result = get_tag_stats_command.execute()

    if get_tag_stats_command.successful:
        return jsonify({"status": "success", "result": result}), 200
    else:
        return (
            jsonify({"status": "failed", "messages": get_tag_stats_command.messages}),
            400,
        )


@stats_routes.route("/user", methods=["GET"])
@jwt_required()
def get_my_stats():
    args = request.args
    required_params = {"start_date", "end_date"}
    public_address = get_jwt_identity()
    if not all(elem in args.keys() for elem in required_params):
        return (
            jsonify(
                {
                    "status": "failed",
                    "message": "Invalid input body. Expected query parameters :{0}".format(
                        required_params
                    ),
                }
            ),
            400,
        )

    entity_type = args.get("entity_type") or "image"
    my_stats_command = UserStatsCommand(entity_type)
    try:
        my_stats_command.input = {
            "public_address": public_address,
            "start_date": args.get("start_date"),
            "end_date": args.get("end_date"),
        }
        response = my_stats_command.execute()
        if my_stats_command.successful:
            return {"status": "success", "result": response}, 200
        else:
            return (
                jsonify({"status": "failed", "messages": my_stats_command.messages}),
                400,
            )
    except ValueError as e:
        logging.error(e, exc_info=True)
        return (
            jsonify(
                {
                    "status": "failed",
                    "messages": ["Value error: Please contact support team."],
                }
            ),
            400,
        )
    except Exception as e:
        return (
            jsonify(
                {
                    "status": "failed",
                    "messages": ["Please contact support team.", e.message],
                }
            ),
            400,
        )


@stats_routes.route("/overall-graph", methods=["GET"])
def get_overall_graph_stats():
    args = request.args
    required_params = {"start_date", "end_date"}
    if not all(elem in args.keys() for elem in required_params):
        return (
            jsonify(
                {
                    "status": "failed",
                    "message": "Invalid input body. Expected query parameters :{0}".format(
                        required_params
                    ),
                }
            ),
            400,
        )
    try:
        entity_type = args.get("entity_type") or "image"
        overall_stats_c = OverallStats2Command(entity_type)

        overall_stats_c.input = {
            "start_date": args.get("start_date"),
            "end_date": args.get("end_date"),
        }
        response = overall_stats_c.execute()
        if overall_stats_c.successful:
            return {"status": "success", "result": response}, 200
        else:
            return (
                jsonify({"status": "failed", "messages": overall_stats_c.messages}),
                400,
            )
    except ValueError:
        return (
            jsonify(
                {
                    "status": "failed",
                    "messages": ["Value error: Please check if input is correct"],
                }
            ),
            400,
        )
    except Exception as e:
        logging.error(e, exc_info=True)
        return (
            jsonify(
                {
                    "status": "failed",
                    "messages": [
                        "Unhandled internal error. Please contact support team."
                    ],
                }
            ),
            400,
        )


@stats_routes.route("/user-graph", methods=["GET"])
@jwt_required()
def get_user_graph_stats():
    args = request.args
    required_params = {"start_date", "end_date"}
    public_address = get_jwt_identity()
    if not all(elem in args.keys() for elem in required_params):
        return (
            jsonify(
                {
                    "status": "failed",
                    "message": "Invalid input body. Expected query parameters :{0}".format(
                        required_params
                    ),
                }
            ),
            400,
        )
    try:
        entity_type = args.get("entity_type") or "image"
        user_stats_graph_command = UserStats2Command(entity_type)

        user_stats_graph_command.input = {
            "public_address": public_address,
            "start_date": args.get("start_date"),
            "end_date": args.get("end_date"),
        }
        response = user_stats_graph_command.execute()
        if user_stats_graph_command.successful:
            return {"status": "success", "result": response}, 200
        else:
            return (
                jsonify(
                    {"status": "failed", "messages": user_stats_graph_command.messages}
                ),
                400,
            )
    except ValueError:
        return (
            jsonify(
                {
                    "status": "failed",
                    "messages": ["Value error: Please check if input is correct"],
                }
            ),
            400,
        )
    except Exception as e:
        return (
            jsonify(
                {
                    "status": "failed",
                    "messages": ["Please contact support team.", str(e)],
                }
            ),
            400,
        )


@stats_routes.route("/tags", methods=["GET"])
def get_tag_stats_by_bounty():
    args = request.args

    bounty_name = args.get("bounty")

    get_tag_stats_by_bounty_command = GetTagStatsByBountyCommand(bounty_name)
    result = get_tag_stats_by_bounty_command.execute()

    if get_tag_stats_by_bounty_command.successful:
        return jsonify({"status": "success", "result": result}), 200
    else:
        return (
            jsonify({"status": "failed", "messages": get_tag_stats_by_bounty_command.messages}),
            400,
        )


@stats_routes.route("/", methods=["GET"])
def get_stats():
    args = request.args
    source = args.get("source")

    c_entity_count = GetEntityCountBySource(source)
    result_entity_count = c_entity_count.execute()

    c_entity_uploads_per_hour = GetEntityUploadsPerHour(source)
    result_entity_uploads_per_hour = c_entity_uploads_per_hour.execute()

    c_handshake_per_hour = GetHandShakesPerHour(source)
    result_handshake_per_hour = c_handshake_per_hour.execute()

    rewards = [{'type': 'image', 'value': 1}, {'type': 'audio', 'value': 1}, {'type': 'video', 'value': 1}]

    return jsonify({'entity_counts': result_entity_count, 'handshakes_per_hour': result_handshake_per_hour,
                    'handshake_count': len(result_handshake_per_hour), 'rewards': rewards,
                    "entity_uploads_per_hour": result_entity_uploads_per_hour}), 200


@stats_routes.route("/events", methods=["GET"])
def get_events():
    args = request.args
    source = args.get("source")
    include_entities = args.get("entities", type=json.loads, default=True)
    include_handshakes = args.get("handshakes", type=json.loads, default=True)

    start_time = args.get("start-time")
    end_time = args.get("end-time")

    start_time = datetime.datetime.strptime(start_time, "%d-%m-%Y %H:%M:%S")
    end_time = datetime.datetime.strptime(end_time, "%d-%m-%Y %H:%M:%S")

    result_all_entities = []
    if include_entities:
        c_all_entities = GetEntityAllEntities(source, start_time, end_time)
        result_all_entities = c_all_entities.execute()

    result_all_handshakes = []
    if include_handshakes:
        c_all_handshakes = GetHandShakesByTime(source, start_time, end_time)
        result_all_handshakes = c_all_handshakes.execute()

    return jsonify({'entities': result_all_entities, 'handshakes': result_all_handshakes}), 200


@stats_routes.route("/success-rate", methods=["GET"])
@jwt_required()
def get_user_success_rate():
    public_address = get_jwt_identity()
    c = SuccessRate(public_address)
    result = c.execute()
    return jsonify(result), 200


@stats_routes.route("/classifications", methods=["GET"])
def get_classification_accuracy():
    c = GetClassificationAccuracy()
    result = c.execute()
    return jsonify(result), 200


@stats_routes.route("/reduced", methods=["GET"])
def get_reduced_stats():
    args = request.args
    db_name = args.get("db-name")
    design_doc = args.get("design-doc")
    view_name = args.get("view")

    c = QueryViewCommandReduced(db_name=DatabaseName[db_name], design_doc=design_doc, view_name=view_name)
    result = c.execute()
    return jsonify(result), 200
