from flask import Blueprint, request
import json

from commands.staticdata.get_words import GetWordsByTypeCommand
from commands.users.get_user_count_command import GetUserCountCommand

staticdata_routes = Blueprint('staticdata_routes', __name__)


@staticdata_routes.route('/staticdata/tags', methods=["GET"])
def get_words_by_types():
    get_words_command = GetWordsByTypeCommand()
    get_words_command.input = {
        'type': request.args.get('type')
    }
    words = get_words_command.execute()

    if not get_words_command.successful:
        return json.dumps({'status': 'failed', 'messages': get_words_command.messages}), 400
    return json.dumps({'status': 'success', 'result': words}), 200


@staticdata_routes.route('/staticdata/user-count', methods=["GET"])
def get_user_count():
    get_user_count_command1 = GetUserCountCommand()
    result = get_user_count_command1.execute()

    if not get_user_count_command1.successful:
        return json.dumps({'status': 'failed', 'messages': get_user_count_command1.messages}), 400
    return json.dumps({"status": "success", 'result': result}), 200
