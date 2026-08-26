from flask import Blueprint, request, jsonify, send_file
from flask_jwt_extended import jwt_required, get_jwt_identity
import json
from commands.challenges.add_new_challenge_command import AddNewChallengeCommand
from commands.challenges.get_all_challenges_command import GetAllChallengesCommand
from commands.challenges.update_challenge_command import UpdateChallengeCommand

challenges_routes = Blueprint("challenges_routes", __name__)


@challenges_routes.route("/", methods=["GET"])
def get_challenges():
    get_all_challenges_command = GetAllChallengesCommand()
    result = get_all_challenges_command.execute()
    if not get_all_challenges_command.successful:
        return (
            jsonify(
                {"status": "failed", "messages": get_all_challenges_command.messages}
            ),
            400,
        )
    return jsonify(result), 200


@challenges_routes.route("/upload", methods=["POST"])
@jwt_required()
def upload_challenges():
    required_params = ["name", "status", "rules"]
    data = json.loads(request.data)

    if not all(elem in data.keys() for elem in required_params):
        return (
            jsonify(
                {
                    "status": "failed",
                    "message": "Invalid input body. Expected keys :{0}".format(
                        required_params
                    ),
                }
            ),
            400,
        )

    add_new_challenge_command = AddNewChallengeCommand()
    add_new_challenge_command.input = {
        "name": data.get("name"),
        "status": data.get("status"),
        "description": data.get("description", None),
        "rules": data.get("rules"),
    }
    result = add_new_challenge_command.execute()
    if not add_new_challenge_command.successful:
        return (
            jsonify(
                {"status": "failed", "messages": add_new_challenge_command.messages}
            ),
            400,
        )
    return jsonify(result), 200


# @challenges_routes.route('/update', methods=["POST"])
# @jwt_required()
# def update_challenges():
#     required_params = ["challenge_id", "name", "status", "rules"]
#     data = json.loads(request.data)

#     if not all(elem in data.keys() for elem in required_params):
#         return jsonify(
#             {"status": "failed", "message": "Invalid input body. Expected keys :{0}".format(required_params)}), 400

#     update_challenge_command = UpdateChallengeCommand()
#     update_challenge_command.input = {
#         "challenge_id": data.get("challenge_id"),
#         "name": data.get("name"),
#         "status": data.get("status"),
#         "description": data.get("description", None),
#         "rules": data.get("rules"),
#     }
#     result = update_challenge_command.execute()
#     if not update_challenge_command.successful:
#         return jsonify({'status': 'failed', 'messages': update_challenge_command.messages}), 400
#     return jsonify(result), 200
