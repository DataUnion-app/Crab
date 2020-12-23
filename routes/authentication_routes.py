from flask import Blueprint, render_template, session, abort, request, jsonify
import json
from dao.users_dao import UsersDao
from flask_jwt_extended import (create_access_token, create_refresh_token, jwt_required, jwt_refresh_token_required,
                                get_jwt_identity, get_raw_jwt)
import logging
from config import config
from dao.sessions_dao import SessionsDao

authentication_routes = Blueprint('authenticationRoutes', __name__)

user = config['couchdb']['user']
password = config['couchdb']['password']
db_host = config['couchdb']['db_host']
users_db = config['couchdb']['users_db']
sessions_db = config['couchdb']['sessions_db']

user_dao = UsersDao()
user_dao.set_config(user, password, db_host, users_db)

sessions_dao = SessionsDao()
sessions_dao.set_config(user, password, db_host, sessions_db)


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

    if user_dao.is_access_blocked(public_address):
        resp = jsonify({'status': 'failed', 'message': 'Access is blocked'})
        return resp, 400

    logging.info("Verifying signature for [{}]".format(public_address))
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


@authentication_routes.route('/refresh', methods=['POST'])
@jwt_refresh_token_required
def refresh():
    public_address = get_jwt_identity()

    if user_dao.is_access_blocked(public_address):
        resp = jsonify({'status': 'failed', 'message': 'Access is blocked'})
        return resp, 400
    access_token = create_access_token(identity=public_address)
    result = {
        'access_token': access_token
    }
    return jsonify(result), 200


@authentication_routes.route("/logout", methods=['POST'])
@jwt_required
def logout():
    jti = get_raw_jwt()['jti']
    sessions_dao.add_to_blacklist(jti)
    return jsonify({'message': 'Access token has been revoked'}), 200


@authentication_routes.route("/check", methods=['GET'])
@jwt_required
def check():
    return "Valid Token", 200
