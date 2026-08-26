import json

from flask import Blueprint, jsonify, request
from flask_jwt_extended import get_jwt_identity, jwt_required, get_jwt

from commands.entity_lists.favorites_entity_list_command import (
    FavoriteEntityListsMarkCommand,
    GetFavoriteEntityListsCommand
)
from commands.entity_lists.create_entity_list_command import CreateEntityListCommand, \
    CreateOrUpdateEntityListFromAnnotations
from commands.entity_lists.delete_list_command import DeleteEntityListCommand
from commands.entity_lists.get_user_lists_command import GetUserListsCommand
from commands.entity_lists.merge_entity_list_command import MergeEntityListsCommand
from commands.entity_lists.search_list_command import SearchListCommand, SearchListByIdCommand
from commands.entity_lists.update_entity_list_command import UpdateEntityListCommand
from models.metadata.metadata_models import Source

entity_list_routes = Blueprint("entity_list_routes", __name__)


@entity_list_routes.route("/create", methods=["POST"])
@jwt_required()
def create_list():
    public_address = get_jwt_identity()
    source_info = get_jwt().get("source", Source.default)
    data = json.loads(request.data)
    entity_type = data.get("entity_type")
    visibility = data.get("visibility")
    entity_ids = data.get("entity_ids")
    description = data.get("description")
    name = data.get("name")
    image = data.get("image")

    c = CreateEntityListCommand(public_address, entity_type, visibility, entity_ids, name, description, image, source_info)
    list_id = c.execute()
    if c.successful:
        return jsonify({
            'id': list_id
        }), 200
    else:
        return jsonify({'messages': c.messages}), 400


@entity_list_routes.route("/create-from-annotations", methods=["POST"])
@jwt_required()
def create_list_from_annotations():
    public_address = get_jwt_identity()
    data = json.loads(request.data)
    entity_type = data.get("entity_type")
    visibility = data.get("visibility")
    annotation_type = data.get("annotation_type")
    tags = data.get("tags", [])
    entity_list_id = data.get("entity_list_id")
    image = data.get("image")

    description = data.get("description")
    name = data.get("name")

    c = CreateOrUpdateEntityListFromAnnotations(public_address, entity_type, visibility, name, description,
                                                annotation_type,
                                                tags, entity_list_id, image)
    list_id = c.execute()
    if c.successful:
        return jsonify({
            'id': list_id
        }), 200
    else:
        return jsonify({'messages': c.messages}), 400


@entity_list_routes.route("/", methods=["GET"])
@jwt_required()
def get_list():
    public_address = get_jwt_identity()
    entity_list_id = request.args.get('id', type=str)

    g = SearchListByIdCommand(public_address, entity_list_id)
    result = g.execute()
    if g.successful:
        return jsonify(result), 200
    else:
        return jsonify({'messages': g.messages}), 400


@entity_list_routes.route("/", methods=["DELETE"])
@jwt_required()
def delete_list():
    list_id = request.args.get('id', type=str)
    public_address = get_jwt_identity()

    d = DeleteEntityListCommand(public_address, list_id)
    d.execute()
    if d.successful:
        return jsonify({'id': list_id}), 200
    else:
        return jsonify({'messages': d.messages}), 400


@entity_list_routes.route("/own", methods=["GET"])
@jwt_required()
def fetch_user_list():
    page = request.args.get('page', type=int)
    entity_type = request.args.get('entity_type', type=str)
    public_address = get_jwt_identity()

    g = GetUserListsCommand(public_address, page, entity_type)
    count, result = g.execute()
    if g.successful:
        return jsonify({"result": result, "total_count": count}), 200
    else:
        return jsonify({'messages': g.messages}), 400


@entity_list_routes.route("/update", methods=["POST"])
@jwt_required()
def update_list():
    public_address = get_jwt_identity()
    try:
        data = json.loads(request.data)
        entity_type = data.get("id")
        visibility = data.get("visibility")
        entity_ids = data.get("entity_ids")
        description = data.get("description")
        name = data.get("name")
        image = data.get("image")

        c = UpdateEntityListCommand(public_address, entity_type, entity_ids, visibility, name, description, image)
        c.execute()
        if c.successful:
            return jsonify({'id': entity_type}), 200
        else:
            return jsonify({'messages': c.messages}), 400
    except Exception as e:
        return jsonify({'messages': [str(e)]}), 400


@entity_list_routes.route("/search", methods=["GET"])
def search_list():
    page = request.args.get('page', type=int)
    entity_type = request.args.get('entity_type', type=str)
    entity_list_id = request.args.get('id', type=str)

    c = SearchListCommand(entity_type, entity_list_id, page)
    result = c.execute()
    if c.successful:
        return jsonify({'result': result}), 200
    else:
        return jsonify({'messages': c.messages}), 400


@entity_list_routes.route("/manage-favorites", methods=["POST"])
@jwt_required()
def manage_favorite_entity_list():
    try:
        public_address = get_jwt_identity()
        data = json.loads(request.data)

        entity_list_to_mark = data.get("entity_lists_to_mark", [])
        entity_list_to_unmark = data.get("entity_lists_to_unmark", [])

        favorite_handler = FavoriteEntityListsMarkCommand(public_address,
                                                          entity_list_to_mark,
                                                          entity_list_to_unmark)
        favorite_handler.execute()

        if favorite_handler.successful:
            return jsonify({'status': 'success'}), 200
        else:
            return jsonify({'status': 'failed', 'messages': favorite_handler.messages}), 400
    except Exception as e:
        return jsonify({'messages': [str(e)]}), 400


@entity_list_routes.route("/favorites", methods=["GET"])
@jwt_required()
def get_favorite_entity_lists():
    try:
        public_address = get_jwt_identity()

        favorite_handler = GetFavoriteEntityListsCommand(public_address)

        result = favorite_handler.execute()

        if favorite_handler.successful:
            return jsonify({'status': 'success', 'result': result}), 200
        else:
            return jsonify({'status': 'failed', 'messages': favorite_handler.messages}), 400
    except Exception as e:
        return jsonify({'messages': [str(e)]}), 400


@entity_list_routes.route("/merge", methods=["POST"])
@jwt_required()
def merge_entity_lists():
    try:
        public_address = get_jwt_identity()
        data = json.loads(request.data)

        merge_entity_lists_command = MergeEntityListsCommand(public_address, sources=data.get("sources"),
                                                             destination=data.get("destination"))

        result = merge_entity_lists_command.execute()

        if merge_entity_lists_command.successful:
            return jsonify({'status': 'success', 'result': result}), 200
        else:
            return jsonify({'status': 'failed', 'messages': merge_entity_lists_command.messages}), 400
    except Exception as e:
        return jsonify({'messages': [str(e)]}), 400
