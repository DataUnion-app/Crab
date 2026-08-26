from flask import Blueprint, request, jsonify, send_file
from flask_jwt_extended import jwt_required, get_jwt_identity, get_jwt
import json
from commands.handshake.handshake_commands import (
    GetHandshakeList,
    AddNewHandshakeCommand
)

handshake_routes = Blueprint("handshake_routes", __name__)


@handshake_routes.route("/all", methods=["GET"])
def get_all_handshakes():
    handshake_command = GetHandshakeList()
    result = handshake_command.execute()

    if not handshake_command.successful:
        return (
            jsonify(
                {"status": "failed", "messages": handshake_command.messages}
            ),
            400,
        )
    return jsonify({"status": "success", "result": result}), 200


@handshake_routes.route("/create", methods=["POST"])
@jwt_required()
def create_handshake():
    data = json.loads(request.data)

    completed_by = get_jwt_identity()
    latitude = data.get("latitude", "")
    longitude = data.get("longitude", "")
    initiated_by = data.get("initiated_by", "")
    source_info = get_jwt().get("source", None)

    add_new_handshake_command = AddNewHandshakeCommand(latitude, longitude, initiated_by, completed_by, source_info)

    result = add_new_handshake_command.execute()

    if add_new_handshake_command.successful:
        return jsonify(result), 200
    else:
        result["messages"] = add_new_handshake_command.messages
        return jsonify(result), 400
