from flask import Blueprint, request
import json
from flask_jwt_extended import (jwt_required, get_jwt_identity)

from commands.taxonomy.store_user_response import StoreUserResponse
import logging

taxonomy_routes = Blueprint('taxonomy_routes', __name__)


@taxonomy_routes.route('/store', methods=["POST"])
@jwt_required
def get_data():
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
