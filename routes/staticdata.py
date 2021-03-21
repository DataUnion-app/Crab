from flask import Blueprint
import json

from commands.staticdata.get_banned_words import GetBannedWordsCommand

staticdata_routes = Blueprint('staticdata_routes', __name__)


@staticdata_routes.route('/staticdata/tags', methods=["GET"])
def get_all_tags():
    all_tags = {
        "category1": ["abc", "xyz"]
    }
    return json.dumps(all_tags), 200


@staticdata_routes.route('/staticdata/banned-words', methods=["GET"])
def get_banned_words():
    get_banned_words_command = GetBannedWordsCommand()
    words = get_banned_words_command.execute()
    return json.dumps({'result': words}), 200
