from flask import Blueprint, render_template, session, abort, request, jsonify
import json
from dao.users_dao import UsersDao
from flask_jwt_extended import (create_access_token, create_refresh_token, jwt_required, jwt_refresh_token_required,
                                get_jwt_identity, get_raw_jwt)

authentication_routes = Blueprint('authenticationRoutes', __name__)

user_dao = UsersDao()
user_dao.set_config("admin", "admin", "127.0.0.1:5984", "users")


@authentication_routes.route("/get-nonce", methods=['GET'])
def get_nonce():
    args = request.args
    if "public_address" not in args:
        resp = jsonify({'message': 'Missing parameter `public_address`'})
        return resp, 400

    nonce = user_dao.get_nonce(args["public_address"])

    return jsonify(nonce), 200


@authentication_routes.route("/register", methods=['POST'])
def register():
    data = json.loads(request.data)
    public_address = data.get("public_address")
    if not public_address:
        resp = jsonify({'message': 'Missing parameter `public_address`'})
        return resp, 400

    result = user_dao.get_nonce(public_address)
    if result["status"] == "exists":
        return jsonify({"status": "failed", "message": "already exists"}), 400

    nonce = user_dao.get_nonce_if_not_exists(public_address)
    return jsonify({"status": "success", "nonce": nonce}), 200


@authentication_routes.route("/login", methods=['POST'])
def login():
    data = json.loads(request.data)
    public_address = data.get("public_address")
    signature = data.get("signature")

    if not public_address or not signature:
        resp = jsonify({'status': 'failed', 'message': 'Missing parameters in body `public_address` or `signature`'})
        return resp, 400

    result = user_dao.verify_signature(public_address, signature)
    if not result:
        return jsonify({"message": "Signature invalid"}), 400

    try:

        access_token = create_access_token(identity=public_address)
        refresh_token = create_refresh_token(identity=public_address)
        user_dao.update_nonce(public_address)
        return jsonify({
            'status': 'success',
            'message': 'Public address [{}] registered'.format(public_address),
            'access_token': access_token,
            'refresh_token': refresh_token
        }), 200
    except:
        return {'message': 'Something went wrong'}, 500
