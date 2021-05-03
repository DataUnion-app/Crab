from flask import Blueprint, request, jsonify, send_file

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
