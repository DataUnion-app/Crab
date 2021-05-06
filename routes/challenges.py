from flask import Blueprint, request, jsonify, send_file
from flask_jwt_extended import (jwt_required, get_jwt_identity)
from datetime import datetime
from config import config
import json
from commands.challenges.add_new_challenge_command import AddNewChallengeCommand

challenges_routes = Blueprint('challenges_routes', __name__)


@challenges_routes.route('/', methods=["GET"])
def get_challenges():
    challenges = [{
        "id": "1",
        "name": "Image upload challenge",
        "status": "RUNNING",
        "description": "Sample description",
        "start_date": 1620079806,
        "end_date": 1622758206,
        "rules": "Sample rules"

    }]
    return jsonify({'result': challenges}), 200


@challenges_routes.route('/upload', methods=["POST"])
@jwt_required
def upload_challenges():
    required_params = ["name", "status", "rules"]
    data = json.loads(request.data)

    if not all(elem in data.keys() for elem in required_params):
        return jsonify(
            {"status": "failed", "message": "Invalid input body. Expected keys :{0}".format(required_params)}), 400

    add_new_challenge_command = AddNewChallengeCommand()
    add_new_challenge_command.input = {
        "name": data.get("name"),
        "status": data.get("status"),
        "description": data.get("description", None),
        "rules": data.get("rules"),
    }
    result = add_new_challenge_command.execute()
    if not add_new_challenge_command.successful:
        return jsonify({'status': 'failed', 'messages': add_new_challenge_command.messages}), 400
    return jsonify(result), 200
