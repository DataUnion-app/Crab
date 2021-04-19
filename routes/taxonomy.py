from flask import Blueprint, request, send_file
import json
from flask_jwt_extended import (jwt_required, get_jwt_identity)
import os
from commands.taxonomy.store_user_response import StoreUserResponse
from commands.taxonomy.get_taxonomy_data import GetTaxnomonyData
from commands.taxonomy.get_image_path import GetImagePathCommand

import logging

taxonomy_routes = Blueprint('taxonomy_routes', __name__)


@taxonomy_routes.route('/store', methods=["POST"])
@jwt_required
def store_data():
    public_address = get_jwt_identity()
    try:
        data = json.loads(request.data)
        store_response = StoreUserResponse()
        store_response.input = {
            'public_address': public_address,
            'response': data['response'],
            'image_id': data['image_id']
        }
        store_response.execute()
        if store_response.successful:
            return json.dumps({'status': 'success'}), 200
        else:
            return json.dumps({'status': 'failed', 'messages': store_response.messages}), 400

    except ValueError as e:
        logging.error(e)
        return json.dumps({'status': 'failed', 'messages': ['invalid json body']}), 400


@taxonomy_routes.route('/data', methods=["GET"])
@jwt_required
def get_data():
    public_address = get_jwt_identity()
    try:
        # data = json.loads(request.data)
        get_taxonomy = GetTaxnomonyData()
        get_taxonomy.input = {
            'public_address': public_address
        }
        result = get_taxonomy.execute()
        if get_taxonomy.successful:
            return json.dumps({'status': 'success', 'result': result}), 200
        else:
            return json.dumps({'status': 'failed', 'messages': get_taxonomy.messages}), 400

    except ValueError as e:
        logging.error(e)
        return json.dumps({'status': 'failed', 'messages': ['invalid json body']}), 400


@taxonomy_routes.route('/image', methods=["GET"])
@jwt_required
def get_image():
    public_address = get_jwt_identity()
    args = request.args
    image_id = args.get('image_id')
    if not image_id:
        return json.dumps({'status': 'failed', 'messages': ['Missing parameter `image_id`']}), 400

    get_image_path = GetImagePathCommand()
    get_image_path.input = {
        'public_address': public_address,
        'image_id': image_id
    }

    result = get_image_path.execute()
    if not get_image_path.successful:
        return json.dumps({'status': 'failed', 'messages': get_image_path.messages}), 400

    if os.path.isfile(result):
        return send_file(result)
    else:
        return json.dumps({'status': 'failed', 'error': 'missing_file'}), 400
