from flask import Blueprint, request, send_file, jsonify
import json
from flask_jwt_extended import jwt_required, get_jwt_identity
from commands.taxonomy.store_user_response import StoreUserResponse
from commands.taxonomy.get_taxonomy_data import GetTaxnomonyData
from commands.taxonomy.get_image_path import GetImagePathCommand
from commands.taxonomy.get_label_image_path import GetLabelImagePathCommand
from commands.taxonomy.get_user_stats import GetUserSwipeCommand
from commands.taxonomy.get_overall_stats import GetOverallStatsCommand

import logging

taxonomy_routes = Blueprint("taxonomy_routes", __name__)


@taxonomy_routes.route("/store", methods=["POST"])
@jwt_required()
def store_data():
    public_address = get_jwt_identity()
    try:
        data = json.loads(request.data)
        store_response = StoreUserResponse()
        store_response.input = {
            "public_address": public_address,
            "response": data["response"],
            "image_id": data["image_id"],
        }
        store_response.execute()
        if store_response.successful:
            return json.dumps({"status": "success"}), 200
        else:
            return (
                json.dumps({"status": "failed", "messages": store_response.messages}),
                400,
            )

    except ValueError as e:
        logging.error(e)
        return json.dumps({"status": "failed", "messages": ["invalid json body"]}), 400


@taxonomy_routes.route("/data", methods=["GET"])
@jwt_required()
def get_data():
    public_address = get_jwt_identity()
    try:
        # data = json.loads(request.data)
        get_taxonomy = GetTaxnomonyData()
        get_taxonomy.input = {"public_address": public_address}
        result = get_taxonomy.execute()
        if get_taxonomy.successful:
            return jsonify({"status": "success", "result": result}), 200
        else:
            return (
                json.dumps({"status": "failed", "messages": get_taxonomy.messages}),
                400,
            )

    except ValueError as e:
        logging.error(e)
        return json.dumps({"status": "failed", "messages": ["invalid json body"]}), 400


@taxonomy_routes.route("/image", methods=["GET"])
@jwt_required()
def get_image():
    public_address = get_jwt_identity()
    args = request.args
    image_id = args.get("image_id")
    if not image_id:
        return (
            json.dumps(
                {"status": "failed", "messages": ["Missing parameter `image_id`"]}
            ),
            400,
        )

    get_image_path = GetImagePathCommand()
    get_image_path.input = {"public_address": public_address, "image_id": image_id}

    result = get_image_path.execute()
    if not get_image_path.successful:
        return (
            json.dumps({"status": "failed", "messages": get_image_path.messages}),
            400,
        )

    return send_file(result)


@taxonomy_routes.route("/label", methods=["GET"])
@jwt_required()
def get_label_image():
    public_address = get_jwt_identity()
    args = request.args
    label_id = args.get("label_id")

    get_label_path = GetLabelImagePathCommand()
    get_label_path.input = {"label_id": label_id}

    path = get_label_path.execute()
    if not get_label_path.successful:
        return jsonify({"status": "failed", "messages": get_label_path.messages}), 400

    return send_file(path)


@taxonomy_routes.route("/user-stats", methods=["GET"])
@jwt_required()
def get_user_swipe_stats():
    public_address = get_jwt_identity()
    args = request.args

    get_user_swipe_command = GetUserSwipeCommand()
    get_user_swipe_command.input = {
        "public_address": public_address,
        "start_date": args.get("start_date"),
        "end_date": args.get("end_date"),
    }
    response = get_user_swipe_command.execute()
    if get_user_swipe_command.successful:
        return {"status": "success", "result": response}, 200
    else:
        return (
            jsonify({"status": "failed", "messages": get_user_swipe_command.messages}),
            400,
        )


@taxonomy_routes.route("/overall-stats", methods=["GET"])
def get_overall_swipe_stats():
    args = request.args

    get_overall_stats_command = GetOverallStatsCommand()
    get_overall_stats_command.input = {
        "start_date": args.get("start_date"),
        "end_date": args.get("end_date"),
    }
    response = get_overall_stats_command.execute()
    if get_overall_stats_command.successful:
        return {"status": "success", "result": response}, 200
    else:
        return (
            jsonify(
                {"status": "failed", "messages": get_overall_stats_command.messages}
            ),
            400,
        )
