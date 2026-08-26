from flask import Blueprint, request, jsonify
import json

from flask_jwt_extended import jwt_required, get_jwt_identity

from commands.query_view_command import ViewQueryType, QueryViewCommand
from commands.staticdata.get_words import GetWordsByTypeCommand
from commands.users.get_user_count_command import GetUserCountCommand
from models.db_name import DatabaseName

staticdata_routes = Blueprint("staticdata_routes", __name__)


@staticdata_routes.route("/staticdata/tags", methods=["GET"])
def get_words_by_types():
    get_words_command = GetWordsByTypeCommand()
    get_words_command.input = {"type": request.args.get("type")}
    words = get_words_command.execute()

    if not get_words_command.successful:
        return (
            json.dumps({"status": "failed", "messages": get_words_command.messages}),
            400,
        )
    return json.dumps({"status": "success", "result": words}), 200


@staticdata_routes.route("/staticdata/user-count", methods=["GET"])
def get_user_count():
    get_user_count_command1 = GetUserCountCommand()
    result = get_user_count_command1.execute()

    if not get_user_count_command1.successful:
        return (
            json.dumps(
                {"status": "failed", "messages": get_user_count_command1.messages}
            ),
            400,
        )
    return json.dumps({"status": "success", "result": result}), 200


@staticdata_routes.route("/staticdata/query-view", methods=["GET"])
@jwt_required()
def query_view():
    public_address = get_jwt_identity()
    view_name = request.args.get('view')
    design_doc = request.args.get('design-doc')
    query_type = ViewQueryType[request.args.get("query-type")]
    doc_id = request.args.get("doc_id")
    c = QueryViewCommand(public_address, DatabaseName.static_data, design_doc, view_name, query_type, doc_id)
    result = c.execute()
    if c.successful:
        return jsonify({"result": result}), 200
    else:
        return jsonify({"messages": c.messages}), 400
