from flask import Blueprint, request
import json

from commands.staticdata.get_words import GetWordsByTypeCommand

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
