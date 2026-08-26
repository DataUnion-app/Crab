from flask import Blueprint, request, jsonify, send_file
import json
import re
from flask_jwt_extended import (
    create_access_token,
    create_refresh_token,
    jwt_required,
    get_jwt_identity, get_jwt,
    verify_jwt_in_request,
)
from jwt import InvalidSignatureError
from werkzeug.security import check_password_hash
from werkzeug.utils import secure_filename
import logging
from jsonschema import validate, ValidationError

from web3 import Web3
from commands.query_view_command import ViewQueryType, QueryViewCommand
from commands.users.manage_referral_link import GetReferralLink
from commands.dataunions.wedatanation.avatar_management import ReserveUserAvatarCommand, StopAvatarGenerationTask
from commands.users.get_agreegated_data_unverified_recycler import GetAggregatedDataUnverifiedRecyclerCommand
from commands.users.get_agreegated_data_verified_creator import GetAggregatedDataVerifiedCreatorCommand
from commands.users.get_agreegated_data_verified_storer import GetAggregatedDataVerifiedStorerCommand
from commands.users.get_agreegated_data_unverified_creator import GetAggregatedDataUnverifiedCreatorCommand
from commands.users.get_agreegated_data_collector import GetAggregatedDataCollectorCommand
from commands.users.get_agreegated_data_recycler import GetAggregatedDataRecyclerCommand
from commands.users.get_agreegated_data_unverified_storer import GetAggregatedDataUnverifiedStorerCommand
from commands.users.users_commands import GetUsersSortbyRewardsClaims
from decorators.permission import requires_user_role
from models.User import USER_ROLE, TeamType, UserRoleType, UserStatus
from dao.users_dao import user_dao
from dao.bounty_dao import bounty_dao
from dao.metadata_dao import image_metadata_dao
from dao.entity_list_dao import entity_list_dao
from dao.metadata_dao import image_metadata_dao
from dao.rewards_dao import rewards_dao
from dao.bounty_dao import bounty_dao
from dao.sessions_dao import sessions_dao
from dao.incident_dao import incident_dao
from dao.missions_dao import missions_dao
from dao.qrcode_dao import qrcode_dao
from models.db_name import DatabaseName
from task_handler.worker import build_user_avatar
from models.metadata.metadata_models import Source
from commands.rewards.claim_reward_command import ClaimRewardCommand
from models.metadata.metadata_models import EntityType
from config import config
from security.jwt_compat import decode_legacy_refresh
import random
import os
import time

# Define allowed image file extensions
ALLOWED_EXTENSIONS = {'jpg', 'jpeg', 'png', 'gif'}

authentication_routes = Blueprint("authenticationRoutes", __name__)

APPLICATION_SOURCE = Source(config["application"].get("app_name"))
if APPLICATION_SOURCE == Source.default:
    raise RuntimeError("application.app_name must name a supported DataUnion source")

def canonical_wallet_address(address):
    try:
        address = Web3.to_checksum_address(address)
        return {
            "address": address,
            "wallet": "eth"
        }
    except:
        return {
            "address": None
        }

def validate_email(email):  
    if re.match(r"[^@]+@[^@]+\.[^@]+", email):  
        return True  
    return False  

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@authentication_routes.route('/set_profile_image', methods=['POST'])
@jwt_required()
def set_profile_image():
    try:
        # Directory to store profile images (update to your preferred directory)
        UPLOAD_FOLDER = 'profile_images'
        
        # Get Form Elements from request
        uploaded_file = request.files.get('file')
        
        # Get User Private Address from access token 
        public_address = get_jwt_identity()
        
        # Create Directory Path for profile images
        dir_path = os.path.join(
                os.path.abspath(os.curdir),
                config["application"]["upload_folder"],
                public_address, UPLOAD_FOLDER
            )
        if not os.path.exists(dir_path):
            os.makedirs(dir_path)

        user = user_dao.get_by_public_address(public_address)
        user_id = user['result'][0]['_id']

        if uploaded_file and allowed_file(uploaded_file.filename):
            filename = secure_filename(uploaded_file.filename)
            filepath = os.path.join(dir_path, filename)

            # Save the uploaded file to the server
            uploaded_file.save(filepath)
            relative_filepath = os.path.join(
                config["application"]["upload_folder"],
                public_address, UPLOAD_FOLDER, filename
            )
            # Set the profile image path in the user's database
            user = user_dao.set_profile_image(user_id, relative_filepath)

            if user:
                return jsonify({"message": "Profile image set successfully", "image":relative_filepath}), 200
            else:
                return jsonify({"error": "Failed to set profile image"}), 500
        else:
            return jsonify({"error": "Invalid request parameters or file format"}), 400

    except Exception as e:
        return jsonify({"error": str(e)}), 500

@authentication_routes.route('/get_profile_image/<public_address>', methods=['GET'])
def get_profile_image(public_address):
    if True:
        user = user_dao.get_by_public_address(public_address=public_address)
        user = user["result"]

        if not user:
            resp = jsonify({"status": "failed", "message": "User not found"})
            return resp, 401

        user = user[0]

        if user and 'profile' in user and user['profile'] and 'profileImage' in user['profile']:
            image_path = user['profile']['profileImage']

            if os.path.isfile(image_path):
                return send_file(image_path, as_attachment=True)

        return send_file('public/user.png', as_attachment=True)

    # except Exception as e:
    #    return jsonify({"error": str(e)}), 500

@authentication_routes.route("/get-nonce", methods=["GET"])
def get_nonce():
    args = request.args
    if "public_address" not in args:
        resp = jsonify({"message": "Missing parameter `public_address`"})
        return resp, 400

    public_address = canonical_wallet_address(args["public_address"])["address"]

    nonce = user_dao.get_nonce(public_address)
    return jsonify(nonce), 200


@authentication_routes.route("/register", methods=["POST"])
def register():
    data = json.loads(request.data)
    public_address = canonical_wallet_address(data.get("public_address"))["address"]

    if not public_address:
        resp = jsonify({"message": "Missing parameter `public_address`"})
        return resp, 400

    result = user_dao.get_nonce(public_address)
    if result["status"] == "exists":
        return jsonify({"status": "failed", "message": "already exists"}), 400

    referral_id = data.get("referral_id")
    nonce, referrer_public_address = user_dao.register_and_get_nonce_if_not_exists(
        public_address, referral_id, UserRoleType.User
    )
    
    return jsonify({"status": "success", "nonce": nonce}), 200


@authentication_routes.route("/register-creator", methods=["POST"])
def register_creator():
    data = request.form
    public_address = canonical_wallet_address(data.get("public_address"))["address"]

    if not public_address:
        resp = jsonify({"message": "Missing parameter `public_address`"})
        return resp, 400

    result = user_dao.get_nonce(public_address)
    if result["status"] == "exists":
        return jsonify({"status": "failed", "message": "already exists"}), 400

    # Validate profile against the schema
    if validate_email(request.form.get('email')) == False:
        return jsonify({
            'status': 'failed',
            'messages': "Invalid email format. ",
        }), 400

    profile = {
        "email": request.form.get('email'),
        "company_title": request.form.get('company_title'),
        "address": request.form.get('address'),
        "country": request.form.get('country'),
    }

    referral_id = data.get("referral_id")

    nonce, referrer_public_address = user_dao.register_and_get_nonce_if_not_exists(public_address, referral_id, UserRoleType.Creator, profile)

    # Set profile image
    user = user_dao.get_by_public_address(public_address)
    user_id = user['result'][0]['_id']
    UPLOAD_FOLDER = 'profile_images'
    uploaded_file = request.files.get('image')

    dir_path = os.path.join(
            os.path.abspath(os.curdir),
            config["application"]["upload_folder"],
            public_address, UPLOAD_FOLDER
        )
    if not os.path.exists(dir_path):
        os.makedirs(dir_path)

    if uploaded_file and allowed_file(uploaded_file.filename):
        filename = secure_filename(uploaded_file.filename)
        filepath = os.path.join(dir_path, filename)

        # Save the uploaded file to the server
        uploaded_file.save(filepath)
        relative_filepath = os.path.join(
            config["application"]["upload_folder"],
            public_address, UPLOAD_FOLDER, filename
        )
        # Set the profile image path in the user's database
        user_dao.set_profile_image(user_id, relative_filepath)

    return jsonify({"status": "success", "nonce": nonce}), 200

@authentication_routes.route("/register-storer", methods=["POST"])
def register_storer():
    data = request.form
    public_address = canonical_wallet_address(data.get("public_address"))["address"]

    if not public_address:
        resp = jsonify({"message": "Missing parameter `public_address`"})
        return resp, 400

    result = user_dao.get_nonce(public_address)
    if result["status"] == "exists":
        return jsonify({"status": "failed", "message": "already exists"}), 400

    profile = {
        "name": data.get('name'),
        "address": data.get('address'),
        "geocode": {
            "lat": data.get('lat'),
            "lng": data.get('lng'),
        },
        "postalCode": data.get('postalCode'),
        "city": data.get('city'),
        "country": data.get('country'),
        "worktime": data.get('worktime'),
        "storageSpace": data.get('storageSpace'),
    }

    referral_id = data.get("referral_id")

    nonce, referrer_public_address = user_dao.register_and_get_nonce_if_not_exists(public_address, referral_id, UserRoleType.Storer, profile)

    return jsonify({"status": "success", "nonce": nonce}), 200

@authentication_routes.route("/register-collector", methods=["POST"])
def register_collector():
    data = request.form
    public_address = canonical_wallet_address(data.get("public_address"))["address"]

    if not public_address:
        resp = jsonify({"message": "Missing parameter `public_address`"})
        return resp, 400

    result = user_dao.get_nonce(public_address)
    if result["status"] == "exists":
        return jsonify({"status": "failed", "message": "already exists"}), 400

    profile = {
        "first_name": data.get("first_name"),
        "last_name": data.get("last_name"),
    }

    referral_id = data.get("referral_id")

    nonce, referrer_public_address = user_dao.register_and_get_nonce_if_not_exists(public_address, referral_id, UserRoleType.User, profile)

    # Set profile image
    user = user_dao.get_by_public_address(public_address)
    user_id = user['result'][0]['_id']

    UPLOAD_FOLDER = 'profile_images'
    uploaded_file = request.files.get('image')

    dir_path = os.path.join(
            os.path.abspath(os.curdir),
            config["application"]["upload_folder"],
            public_address, UPLOAD_FOLDER
        )
    if not os.path.exists(dir_path):
        os.makedirs(dir_path)

    if uploaded_file and allowed_file(uploaded_file.filename):
        filename = secure_filename(uploaded_file.filename)
        filepath = os.path.join(dir_path, filename)

        # Save the uploaded file to the server
        uploaded_file.save(filepath)
        relative_filepath = os.path.join(
            config["application"]["upload_folder"],
            public_address, UPLOAD_FOLDER, filename
        )
        # Set the profile image path in the user's database
        user_dao.set_profile_image(user_id, relative_filepath)

    return jsonify({"status": "success", "nonce": nonce}), 200

@authentication_routes.route("/register_external", methods=["POST"])
def register_external():
    data = json.loads(request.data)
    public_address = data.get("public_address")
    if not public_address:
        resp = jsonify({"message": "Missing parameter `public_address`"})
        return resp, 400

    result = user_dao.get_nonce(public_address)
    if result["status"] == "exists":
        return jsonify({"status": "failed", "message": "already exists"}), 400

    nonce = user_dao.get_nonce_if_not_exists_external(public_address)
    return jsonify({"status": "success", "nonce": nonce}), 200


@authentication_routes.route("/get_or_create_username", methods=["POST"])
@jwt_required()
def get_or_create_username():
    public_address = get_jwt_identity()
    from_username = user_dao.get_or_create_username(public_address)
    return jsonify({"status": "success", "username": from_username}), 200


@authentication_routes.route("/update_username", methods=["POST"])
@jwt_required()
def update_username():
    data = request.get_json(silent=True) or {}
    username = data.get("username")
    if not isinstance(username, str):
        return jsonify({"message": "Missing parameter `username`"}), 400

    username = username.strip()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{2,49}", username):
        return jsonify({
            "message": "Username must be 3-50 letters, numbers, dots, dashes, or underscores"
        }), 400

    public_address = get_jwt_identity()
    username = user_dao.update_username(public_address, username)
    if username is None:
        return jsonify({"message": "Username already exists"}), 409
    return jsonify({"status": "success", "username": username}), 200


@authentication_routes.route("/login", methods=["POST"])
def login():
    data = json.loads(request.data)
    wallet_address = canonical_wallet_address(data.get("public_address"))
    public_address = wallet_address["address"]
    signature = data.get("signature")

    if not public_address or not signature:
        resp = jsonify(
            {
                "status": "failed",
                "message": "Missing parameters in body `public_address` or `signature`",
            }
        )
        return resp, 400
    user = user_dao.get_by_public_address(public_address=public_address)
    user = user["result"]

    if not user:
        resp = jsonify({"status": "failed", "message": "User not found"})
        return resp, 401

    user = user[0]

    if user["is_access_blocked"]:
        resp = jsonify({"status": "failed", "message": "Access is blocked"})
        return resp, 400

    logging.info("Verifying signature for [{}]".format(public_address))
    result = user_dao.verify_signature(public_address, signature, wallet_address["wallet"])
    if not result:
        return jsonify({"message": "Signature invalid"}), 400

    try:
        is_admin = True if USER_ROLE['ADMIN'] in user.get("claims", []) else False

        user_claims = {
            "is_admin": is_admin,
            "source": APPLICATION_SOURCE.value,
        }
        user_claims['roles'] = user['claims']
        access_token = create_access_token(identity=public_address,
                                           additional_claims=user_claims)
        refresh_token = create_refresh_token(identity=public_address,
                                             additional_claims=user_claims)
        user_dao.update_nonce(public_address)

        return (
            jsonify(
                {
                    "status": "success",
                    "message": "Public address [{}] registered".format(public_address),
                    "roles": user['claims'],
                    "id": user['_id'],
                    "access_token": access_token,
                    "refresh_token": refresh_token,
                }
            ),
            200,
        )
    except Exception as e:
        logging.exception(e, exc_info=True)
        return {"message": "Something went wrong"}, 500


def _refresh_payload():
    try:
        _, payload = verify_jwt_in_request(refresh=True)
        return payload
    except InvalidSignatureError:
        pass

    application_config = config["application"]
    deadline = application_config.getint("legacy_jwt_refresh_deadline_epoch", fallback=0)
    if time.time() >= deadline:
        return None

    authorization = request.headers.get("Authorization", "").split()
    token = (
        authorization[1]
        if len(authorization) == 2 and authorization[0].lower() == "bearer"
        else ""
    )
    payload = decode_legacy_refresh(
        token,
        application_config.get("legacy_jwt_refresh_secret_string", fallback="").strip(),
        APPLICATION_SOURCE.value,
    )
    if not payload or sessions_dao.is_blacklisted(payload["jti"]):
        return None

    wallet = canonical_wallet_address(payload["sub"])
    if not wallet["address"]:
        return None
    payload["sub"] = wallet["address"]
    return payload


@authentication_routes.route("/refresh", methods=["POST"])
def refresh():
    payload = _refresh_payload()
    if not payload:
        return jsonify({"msg": "Token has expired"}), 401
    public_address = payload["sub"]

    user = user_dao.get_by_public_address(public_address=public_address)
    user = user["result"]

    if not user:
        resp = jsonify({"status": "failed", "message": "User not found"})
        return resp, 401

    user = user[0]

    if user["is_access_blocked"]:
        resp = jsonify({"status": "failed", "message": "Access is blocked"})
        return resp, 400

    is_admin = True if USER_ROLE['ADMIN'] in user.get("claims", []) else False

    user_claims = {
        "is_admin": is_admin,
        "source": APPLICATION_SOURCE.value,
    }
    user_claims['roles'] = user['claims']
    access_token = create_access_token(identity=public_address,
                                       additional_claims=user_claims)

    result = {"access_token": access_token}
    return jsonify(result), 200


@authentication_routes.route("/revoke-refresh-token", methods=["POST"])
def revoke_refresh_token():
    payload = _refresh_payload()
    if not payload:
        return jsonify({"msg": "Token has expired"}), 401
    sessions_dao.add_to_blacklist(payload["jti"])
    return jsonify({"message": "Refresh token has been revoked"}), 200


@authentication_routes.route("/logout", methods=["POST"])
@jwt_required()
def logout():
    jti = get_jwt()["jti"]
    sessions_dao.add_to_blacklist(jti)
    return jsonify({"message": "Access token has been revoked"}), 200


@authentication_routes.route("/usage-flag", methods=["POST"])
@jwt_required()
def set_guideline_flag():
    data = json.loads(request.data)

    if not data.get("flag"):
        return jsonify({"message": 'Missing property in json body "flag"'}), 400

    flag = data.get("flag")

    if not (flag == "REJECTED" or flag == "ACCEPTED"):
        return (
            jsonify(
                {
                    "message": 'Invalid property in json body "flag". Valid values are: "ACCEPTED" or "REJECTED"'
                }
            ),
            400,
        )

    public_address = get_jwt_identity()
    user_dao.set_flag(public_address, flag)
    return jsonify({"status": "success"}), 200


@authentication_routes.route("/usage-flag", methods=["GET"])
@jwt_required()
def check_guideline_flag():
    public_address = get_jwt_identity()
    flag = user_dao.get_flag(public_address)
    return jsonify({"usage_flag": flag}), 200


@authentication_routes.route("/guidelines-acceptance", methods=["GET", "POST"])
@jwt_required()
def guidelines_acceptance_flag():
    if request.method == 'POST':
        data = json.loads(request.data)

        if not data.get("flag"):
            return jsonify({"message": 'Missing property in json body "flag"'}), 400

        acceptance_flag = data.get("flag")

        if acceptance_flag not in ["REJECTED", "ACCEPTED"]:
            return (
                jsonify(
                    {
                        "message": 'Invalid property in json body "flag". '
                                   'Valid values are: "ACCEPTED" or "REJECTED"'
                    }
                ),
                400,
            )

        public_address = get_jwt_identity()
        user_dao.set_flag(public_address=public_address,
                          flag=acceptance_flag,
                          flag_type="guidelines_acceptance_flag")
        return jsonify({"status": "success"}), 200

    public_address = get_jwt_identity()
    flag = user_dao.get_flag(public_address=public_address,
                             flag_type="guidelines_acceptance_flag")

    return jsonify({"guidelines_acceptance_flag": flag}), 200


@authentication_routes.route("/api/v1/user/query-view", methods=["GET"])
@jwt_required()
def query_view():
    public_address = get_jwt_identity()
    view_name = request.args.get('view')
    design_doc = request.args.get('design-doc')
    query_type = ViewQueryType[request.args.get("query-type")]
    doc_id = request.args.get("doc_id")
    c = QueryViewCommand(public_address, DatabaseName.users, design_doc, view_name, query_type, doc_id)
    result = c.execute()
    if c.successful:
        return jsonify({"result": result}), 200
    else:
        return jsonify({"messages": c.messages}), 400


@authentication_routes.route("/check", methods=["GET"])
@jwt_required()
def check():
    return "Valid Token", 200


@authentication_routes.route("/api/v1/user/avatar/generate", methods=["POST"])
@jwt_required()
def generate_avatar():
    if APPLICATION_SOURCE != Source.wedatanation:
        return jsonify({'status': 'failed', 'messages': ['Avatar generation is unavailable']}), 404
    public_address = get_jwt_identity()
    try:
        param = {'public_address': public_address}
        build_user_avatar.apply_async(args=[param])
        logging.info("Celery task for adding exif and verifying image is started...")
    except Exception as e:
        logging.exception(f"Unable to build profile for [{public_address}]", exc_info=e)
        return jsonify({'status': 'failed', 'messages': [str(e)]}), 400

    return jsonify({'status': 'success'}), 200


@authentication_routes.route("/api/v1/user/avatar/cancel", methods=["POST"])
@jwt_required()
def cancel_avatar_generation_task():
    if APPLICATION_SOURCE != Source.wedatanation:
        return jsonify({'status': 'failed', 'messages': ['Avatar generation is unavailable']}), 404
    public_address = get_jwt_identity()
    r_c = StopAvatarGenerationTask(public_address)
    result = r_c.execute()
    if r_c.successful:
        return jsonify({'status': 'success', 'result': result}), 200
    else:
        return jsonify({'status': 'failed', 'messages': r_c.messages}), 400


@authentication_routes.route("/api/v1/user/reserve-avatar", methods=["POST"])
@jwt_required()
def reserve_avatars():
    if APPLICATION_SOURCE != Source.wedatanation:
        return jsonify({'status': 'failed', 'messages': ['Avatar generation is unavailable']}), 404
    public_address = get_jwt_identity()
    data = request.json
    r_c = ReserveUserAvatarCommand(public_address, data['image_url'])
    result = r_c.execute()
    if r_c.successful:
        return jsonify({'status': 'success', 'result': result}), 200
    else:
        return jsonify({'status': 'failed', 'messages': r_c.messages}), 400


@authentication_routes.route("/api/v1/user/referral-id", methods=["GET"])
@jwt_required()
def get_referral_link():
    public_address = get_jwt_identity()
    c = GetReferralLink(public_address)
    result = c.execute()
    if c.successful:
        return jsonify({"result": result}), 200
    else:
        return jsonify({"messages": c.messages}), 400

@authentication_routes.route("/api/v1/profile", methods=["PUT"])
@jwt_required()
def set_user_profile():
    try:
        profile = json.loads(request.data)

        public_address = get_jwt_identity()

        user = user_dao.get_by_public_address(public_address)
        user_id = user['result'][0]['_id']

        # Set profile
        user_dao.set_profile(user_id, profile)
        return jsonify({'status': 'success'}), 200

    except Exception as e:
        return jsonify({
            'status': 'failed',
            'messages': str(e)
        }), 400

@authentication_routes.route("/api/v1/profile", methods=["GET"])
@jwt_required()
def get_user_profile():
    public_address = get_jwt_identity()

    user = user_dao.get_by_public_address(public_address)
    user = user['result'][0]

    return jsonify({
        'status': 'success',
        'result': {
            'id': user['_id'],
            'roles': user.get('claims', []),
            'status': user['status'],
            'profile': user.get('profile', {})
        }
    }), 200

@authentication_routes.route("/api/v1/storer/<string:id>", methods=["PUT"])
@requires_user_role(UserRoleType.Recyclium_Admin)
def set_storer_profile(id):
    try:
        profile = json.loads(request.data)

        # Validate profile against the schema
        profile_schema = {
            'type': 'object',
            'properties': {
                'name': {'type': 'string'},
                'address': {'type': 'string'},
                'geocode': {
                    'type': 'object',
                    'properties': {
                        'lat': {'type': 'number'},
                        'lng': {'type': 'number'},
                    },
                    'required': ['lat', 'lng']
                },
                'postalCode': {'type': 'string'},
                'city': {'type': 'string'},
                'country': {'type': 'string'},
                'worktime': {'type': 'string'},
                'storageSpace': {'type': 'number'}
            },
            'required': ['name', 'address', 'geocode', 'postalCode', 'city', 'country', 'worktime', 'storageSpace']
        }
        validate(profile, profile_schema)

        # Check Storer role
        user = user_dao.get_doc_by_id(id)
        has_storer_role = UserRoleType.Storer in user.get('claims', [])
        if not has_storer_role:
            return jsonify({
                'status': 'failed',
                'messages': "The user doesn't have Storer role",
            }), 400

        # Set profile
        user_dao.set_profile(id, profile)
        return jsonify({'status': 'success'}), 200
    except ValidationError as e:
        # profile validation failed
        return jsonify({
            'status': 'failed',
            'messages': str(e)
        }), 400
    except Exception as e:
        return jsonify({
            'status': 'failed',
            'messages': str(e)
        }), 400


@authentication_routes.route("/api/v1/storer/<string:id>", methods=["GET"])
@requires_user_role(UserRoleType.Recyclium_Admin)
def get_storer_profile(id):
    try:
        user = user_dao.get_doc_by_id(id)
        return jsonify({'status': 'success', 'storer': user.get('profile', [])})
    except Exception as e:
        return jsonify({
            'status': 'failed',
            'messages': str(e)
        }), 400


@authentication_routes.route("/api/v1/storers", methods=["POST"])
@requires_user_role(UserRoleType.Recyclium_Admin)
def get_storers():
    data = json.loads(request.data)
    page_no = data.get('page_no')
    per_page = data.get('per_page')
    sort = data.get('sort', 'desc')

    try:
        storers = user_dao.get_storers_rank_by_rewards(page_no, per_page, sort)
        return jsonify({'status': 'success', 'storers': storers})
    except Exception as e:
        return jsonify({
            'status': 'failed',
            'messages': str(e)
        }), 400

@authentication_routes.route("/api/v1/collectors", methods=["POST"])
@requires_user_role(UserRoleType.Recyclium_Admin)
def get_collectors():
    data = json.loads(request.data)
    page_no = data.get('page_no')
    per_page = data.get('per_page')
    sort = data.get('sort', 'desc')

    try:
        collectors = user_dao.get_collectors_rank_by_rewards(page_no, per_page, sort)
        return jsonify({'status': 'success', 'collectors': collectors})
    except Exception as e:
        return jsonify({
            'status': 'failed',
            'messages': str(e)
        }), 400


@authentication_routes.route("/api/v1/creators", methods=["POST"])
@requires_user_role(UserRoleType.Recyclium_Admin)
def get_creators():
    data = json.loads(request.data)
    page_no = data.get('page_no')
    per_page = data.get('per_page')
    sort = data.get('sort', 'desc')

    try:
        creators = user_dao.get_creators_rank_by_rewards(page_no, per_page, sort)
        return jsonify({'status': 'success', 'creators': creators})
    except Exception as e:
        return jsonify({
            'status': 'failed',
            'messages': str(e)
        }), 400

@authentication_routes.route("/api/v1/recyclers", methods=["POST"])
@requires_user_role(UserRoleType.Recyclium_Admin)
def get_recyclers():
    data = json.loads(request.data)
    page_no = data.get('page_no')
    per_page = data.get('per_page')
    sort = data.get('sort', 'desc')

    try:
        recyclers = user_dao.get_all_recyclers(page_no, per_page, sort)
        return jsonify({'status': 'success', 'recyclers': recyclers})
    except Exception as e:
        return jsonify({
            'status': 'failed',
            'messages': str(e)
        }), 400

@authentication_routes.route("/api/v1/creator/<string:id>", methods=["PUT"])
@requires_user_role(UserRoleType.Recyclium_Admin)
def set_creator_profile(id):
    try:
        creator = json.loads(request.data)

        # Validate profile against the schema
        if validate_email(creator["email"]) == False:
            return jsonify({
                'status': 'failed',
                'messages': "Invalid email format. ",
            }), 400
        creator_schema = {
            'type': 'object',
            'properties': {
                'email': {'type': 'string'},
                'company_title': {'type': 'string'},
                'address': {'type': 'string'},
                'country': {'type': 'string'},
            },
            'required': ['email', 'company_title', 'address', 'country']
        }
        validate(creator, creator_schema)

        # Check Creator role
        user = user_dao.get_doc_by_id(id)
        has_creator_role = UserRoleType.Creator in user.get('claims', [])
        if not has_creator_role:
            return jsonify({
                'status': 'failed',
                'messages': "The user doesn't have Creator role",
            }), 400
        
        # Set profile
        user_dao.set_profile(id, creator)
        return jsonify({'status': 'success'}), 200
    except ValidationError as e:
        # creator validation failed
        return jsonify({
            'status': 'failed',
            'messages': str(e)
        }), 400
    except Exception as e:
        return jsonify({
            'status': 'failed',
            'messages': str(e)
        }), 400


@authentication_routes.route("/api/v1/creator/status/<string:id>", methods=["PUT"])
@requires_user_role(UserRoleType.Recyclium_Admin)
def set_creator_status(id):
    try:
        data = json.loads(request.data)
        status = data.get("status")
        if not status:
            return jsonify({
                'status': 'failed',
                'messages': "Missing parameters in body `status`",
            }), 400
        has_status = status in iter(UserStatus)
        if not has_status:
            return jsonify({
                    'status': 'failed',
                    'messages': "Incorrect status value.",
                }), 400
        # set status
        user_dao.set_status(id, status)
        return jsonify({'status': 'success'}), 200
    except Exception as e:
        return jsonify({
            'status': 'failed',
            'messages': str(e)
        }), 400
    
@authentication_routes.route("/api/v1/creator/status/<string:id>", methods=["GET"])
@jwt_required()
def get_creator_status(id):
    try:
        user = user_dao.get_doc_by_id(id)
        return jsonify({'status': get_jwt(), 'creator': user.get('status', [])})
    except Exception as e:
        return jsonify({
            'status': 'failed',
            'messages': str(e)
        }), 400

@authentication_routes.route("/api/v1/creator/<string:id>", methods=["GET"])
@jwt_required()
# @requires_user_role(UserRoleType.Recyclium_Admin)
def get_creator_profile(id):
    user = user_dao.get_doc_by_id(id)
    return jsonify({'status': 'success', 'creator': user.get('profile', [])})

def get_users_by_query(query, role):
    if query == "":
        result = user_dao.get_all_user_DID()["result"]
    else:
        result = user_dao.get_users_by_query(query, role)
    for doc in result:
        public_address = doc["public_address"]
        entity_lists = entity_list_dao.get_entity_lists_by_public_address(public_address)
        doc["scanned_count"] = 0
        doc["stored_count"] = 0
        doc["returned_count"] = 0
        for data in entity_lists:
            doc_id = data["_id"]
            c = QueryViewCommand(public_address, DatabaseName.entity_list, 
                "entity-search-stats", "entity-search-stats", ViewQueryType.user_created_doc_id, doc_id)
            view_result = c.execute()
            if(len(view_result) > 0):
                doc["scanned_count"] += view_result[0]["scanned_count"]
                doc["stored_count"] += view_result[0]["stored_count"]
                doc["returned_count"] += view_result[0]["returned_count"]
    return result

@authentication_routes.route("/api/v1/user", methods=["GET"])
@requires_user_role(UserRoleType.Recyclium_Admin)
def search_user():
    query = request.args.get('query')
    role =  request.args.get('role')
    if role:
        result = get_users_by_query(query, USER_ROLE[role])
        return jsonify({USER_ROLE[role]: result}), 200
    else :
        creators = get_users_by_query(query, USER_ROLE['CREATOR'])
        storers = get_users_by_query(query, USER_ROLE['STORER'])
        collectors = get_users_by_query(query, USER_ROLE['USER'])
        recyclers = get_users_by_query(query, USER_ROLE['RECYCLER'])
        return jsonify({USER_ROLE['RECYCLER']: recyclers, USER_ROLE['CREATOR']: creators, USER_ROLE['STORER']: storers, "collector": collectors}), 200

@authentication_routes.route("/api/v1/users/pending", methods=["GET"])
@jwt_required()
@requires_user_role(UserRoleType.Recyclium_Admin)
def get_new_users():
    page_size = request.args.get('page_size')
    role =  request.args.get('role')
    page =  request.args.get('page')
    page_size = int(page_size) if page_size else 10
    page = int(page)-1 if page else 0
    if page_size < 0 or page < 0 :
        resp = jsonify({"message": "Pagination parameters are incorrect."})
        return resp, 400
    new_users = user_dao.search_by_status_role_pagination( UserStatus.NEW , role, page_size, page ) 
    return jsonify({"status": "success", "pending_users": new_users["result"] }), 200

@authentication_routes.route("/api/v1/user/<string:id>/profile", methods=["PUT"])
@requires_user_role(UserRoleType.Recyclium_Admin)
def set_status_profile(id):
    data = json.loads(request.data)
    status = data.get("status")
    if not status:
        return jsonify({
            'status': 'failed',
            'messages': "Missing parameters in body `status`",
        }), 400
    has_status = status in iter(UserStatus)
    if not has_status:
        return jsonify({
                'status': 'failed',
                'messages': "Incorrect status value.",
            }), 400
    status_reason = data.get("status_reason")
    if not status_reason and status == UserStatus["INACTIVE"]:
        return jsonify({
                'status': 'failed',
                'messages': "Missing parameters in body `status_reason`",
            }), 400
    user = user_dao.get_doc_by_id(id)
    user_dao.set_status_reason(id, status, status_reason)
    return jsonify({'status': 'success'}), 200

@authentication_routes.route("/api/v1/user/<string:id>/profile", methods=["GET"])
@requires_user_role(UserRoleType.Recyclium_Admin)
def get_status_profile(id):
    try:
        user = user_dao.get_doc_by_id(id)
        return jsonify({'status': 'success', 'status': user.get('status'), 'status_reason': user.get('status_reason')})
    except Exception as e:
        return jsonify({
            'status': 'failed',
            'messages': str(e)
        }), 400

@authentication_routes.route("/api/v1/user/incidents", methods=["GET"])
@jwt_required()
# @requires_user_role(UserRoleType.Recyclium_Admin)
def get_incidents():
    try:
        user_id = request.args.get("user_id")
        user = incident_dao.get_by_user_id(user_id)
        if not user_id:
            user = incident_dao.get_all_incidents()
        return jsonify({'status': 'success', 'result': user})
    except Exception as e:
        return jsonify({
            'status': 'failed',
            'messages': str(e)
        }), 400

@authentication_routes.route("/api/v1/user/incident/<string:user_id>", methods=["GET"])
@jwt_required()
# @requires_user_role(UserRoleType.Recyclium_Admin)
def get_incident(user_id):
    try:
        incidents = incident_dao.get_by_user_id(user_id)
        return jsonify({'status': 'success', 'result': incidents})
    except Exception as e:
        return jsonify({
            'status': 'failed',
            'messages': str(e)
        }), 400

@authentication_routes.route("/api/v1/user/incidents", methods=["POST"])
# @requires_user_role(UserRoleType.Recyclium_Admin)
@jwt_required()
def set_incidents():
    data = json.loads(request.data)
    user_id = data.get("user_id")
    description = data.get("description")
    if not user_id:
        return jsonify({
                'status': 'failed',
                'messages': "Missing parameters in body `user_id`",
            }), 400
    if not description:
        return jsonify({
                'status': 'failed',
                'messages': "Missing parameters in body `description`",
            }), 400
    incident_dao.create_incident(user_id, description)
    return jsonify({'status': 'success'}), 200

@authentication_routes.route("/api/v1/user/collector/<string:id>", methods=["PUT"])
@jwt_required()
@requires_user_role(UserRoleType.Recyclium_Admin)
def set_collector_profile(id):
    try:
        data = json.loads(request.data)
        user_name = data.get("user_name")
        if not user_name:
            return jsonify({
                    'status': 'failed',
                    'messages': "Missing parameters in body `user_name`",
                }), 400


        # Check Collector role
        user = user_dao.get_doc_by_id(id)
        has_user_role = UserRoleType.User in user.get('claims', [])
        if not has_user_role:
            return jsonify({
                'status': 'failed',
                'messages': "The user doesn't have Collector role",
            }), 400
        
        # Set profile
        user_dao.set_collector(id, user_name)
        return jsonify({'status': 'success'}), 200
    except Exception as e:
        # collector validation failed
        return jsonify({
            'status': 'failed',
            'messages': str(e)
        }), 400

@authentication_routes.route("/api/v1/users/verified", methods=["GET"])
@jwt_required()
@requires_user_role(UserRoleType.Recyclium_Admin)
def get_verified_users():
    data = json.loads(request.data)
    new_users = user_dao.search_verified_user() 
    return jsonify({"status": "success", "verified_users": new_users["result"] }), 200

@authentication_routes.route("/api/v1/user/did/<string:id>", methods=["PUT"])
@jwt_required()
@requires_user_role(UserRoleType.Recyclium_Admin)
def set_user_DID(id):
    try:
        public_address = get_jwt_identity()
        roles = get_jwt().get("roles")
        data = json.loads(request.data)
        DID = data.get("DID")
        if not DID:
            return jsonify({
                    'status': 'failed',
                    'messages': "Missing parameters in body `DID`",
                }), 400
        user = user_dao.get_doc_by_id(id)
        if len(user) == 0:
            return jsonify({
                    'status': 'failed',
                    'messages': "invalid 'user_id'",
                }), 400
        user_dao.set_DID(id, DID)
        return jsonify({'status': 'success'}), 200
    except Exception as e:
        return jsonify({
            'status': 'failed',
            'messages': str(e)
        }), 400

@authentication_routes.route("/api/v1/user/collector/<string:id>", methods=["GET"])
@requires_user_role(UserRoleType.Recyclium_Admin)
def get_collector_profile(id):
    user = user_dao.get_doc_by_id(id)
    return jsonify({'status': 'success', 'collector': user.get('profile', [])})

@authentication_routes.route("/api/v1/user/did/<string:user_id>", methods=["GET"])
@requires_user_role(UserRoleType.Recyclium_Admin)
def get_user_DID(user_id):
    user = user_dao.get_DID_by_id(user_id)
    return jsonify({'status': 'success', 'User': user["result"]})

@authentication_routes.route("/api/v1/user/get_all_did", methods=["GET"])
@requires_user_role(UserRoleType.Recyclium_Admin)
def get_all_user_DID():
    user = user_dao.get_all_user_DID()
    return jsonify({'status': 'success', 'User': user["result"]})

@authentication_routes.route("/api/v1/user/get_aggregated_data_verified_creator/<string:creator_id>", methods=["GET"])
@requires_user_role(UserRoleType.Recyclium_Admin)
def get_aggregated_data_verified_creator(creator_id):
    c = GetAggregatedDataVerifiedCreatorCommand(creator_id)
    result = c.execute()
    return jsonify({'status': 'success', 'result': result})

@authentication_routes.route("/api/v1/user/get_aggregated_data_unverified_creator/<string:creator_id>", methods=["GET"])
@requires_user_role(UserRoleType.Recyclium_Admin)
def get_aggregated_data_unverified_creator(creator_id):
    c = GetAggregatedDataUnverifiedCreatorCommand(creator_id)
    result = c.execute()
    return jsonify({'status': 'success', 'result': result})

@authentication_routes.route("/api/v1/user/get_aggregated_data_unverified_recycler/<string:recycler_id>", methods=["GET"])
@requires_user_role(UserRoleType.Recyclium_Admin)
def get_aggregated_data_unverified_recycler(recycler_id):
    c = GetAggregatedDataUnverifiedRecyclerCommand(recycler_id)
    result = c.execute()
    return jsonify({'status': 'success', 'result': result})

@authentication_routes.route("/api/v1/user/get_aggregated_data_unverified_storer/<string:storer_id>", methods=["GET"])
@requires_user_role(UserRoleType.Recyclium_Admin)
def get_aggregated_data_unverified_storer(storer_id):
    c = GetAggregatedDataUnverifiedStorerCommand(storer_id)
    result = c.execute()
    return jsonify({'status': 'success', 'result': result})

@authentication_routes.route("/api/v1/user/get_aggregated_data_collector/<string:user_id>", methods=["GET"])
@requires_user_role(UserRoleType.Recyclium_Admin)
def get_aggregated_data_collector_detail(user_id):
    c = GetAggregatedDataCollectorCommand(user_id)
    result = c.execute()
    return jsonify({'status': 'success', 'result': result})

@authentication_routes.route("/api/v1/user/get_aggregated_data_verified_storer/<string:user_id>", methods=["GET"])
@requires_user_role(UserRoleType.Storer)
def get_aggregated_data_verified_storer(user_id):
    c = GetAggregatedDataVerifiedStorerCommand(user_id)
    result = c.execute()
    return jsonify({'status': 'success', 'result': result})

@authentication_routes.route("/api/v1/user/get_collectors_page_in_category", methods=["GET"])
@requires_user_role(UserRoleType.Recyclium_Admin)
def get_collectors_page_in_category():
    try:
        c = GetUsersSortbyRewardsClaims(UserRoleType.User)
        collectors_rank_by_rewards = c.execute()
        verified_collectors = user_dao.search_by_status_role_pagination(UserStatus.VERIFIED, UserRoleType.User)
        verification_queue_collectors = user_dao.search_by_status_role_pagination(UserStatus.NEW, UserRoleType.User)
        return jsonify({
            'status': 'success',
            'result': {
                'top_collectors': collectors_rank_by_rewards,
                'verified_collectors': verified_collectors,
                'verification_queue_collectors': verification_queue_collectors
            }
        })
    except Exception as e:
        return jsonify({
            'status': 'failed',
            'messages': str(e)
        }), 400

@authentication_routes.route("/api/v1/user/get_storers_page_in_category", methods=["GET"])
@requires_user_role(UserRoleType.Recyclium_Admin)
def get_storers_page_in_category():
    try:
        c = GetUsersSortbyRewardsClaims(UserRoleType.Storer)
        storers_rank_by_rewards = c.execute()
        verified_storers = user_dao.search_by_status_role_pagination(UserStatus.VERIFIED, UserRoleType.Storer)
        verification_queue_storers = user_dao.search_by_status_role_pagination(UserStatus.NEW, UserRoleType.Storer)
        return jsonify({
            'status': 'success',
            'result': {
                'top_storers': storers_rank_by_rewards,
                'verified_storers': verified_storers,
                'verification_queue_storers': verification_queue_storers
            }
        })
    except Exception as e:
        return jsonify({
            'status': 'failed',
            'messages': str(e)
        }), 400

@authentication_routes.route("/api/v1/user/get_creators_page_in_category", methods=["GET"])
@requires_user_role(UserRoleType.Recyclium_Admin)
def get_creators_page_in_category():
    try:
        c = GetUsersSortbyRewardsClaims(UserRoleType.Creator)
        creators_rank_by_rewards = c.execute()
        verified_creators = user_dao.search_by_status_role_pagination(UserStatus.VERIFIED, UserRoleType.Creator)
        verification_queue_creators = user_dao.search_by_status_role_pagination(UserStatus.NEW,  UserRoleType.Creator)
        return jsonify({
            'status': 'success',
            'result': {
                'top_creators': creators_rank_by_rewards,
                'verified_creators': verified_creators,
                'verification_queue_creators': verification_queue_creators
            }
        })
    except Exception as e:
        return jsonify({
            'status': 'failed',
            'messages': str(e)
        }), 400

@requires_user_role(UserRoleType.Creator)
def get_all_missions_info():
    user = user_dao.get_all_user_DID()
    return jsonify({'status': 'success', 'User': user["result"]})

@authentication_routes.route("/api/v1/user/set_storer_rating", methods=["POST"])
@jwt_required()
@requires_user_role(UserRoleType.User)
def storer_rating():
    try:
        data = json.loads(request.data)

        collector_address = get_jwt_identity()
        
        # Check if the storer exists and has the 'storer' claim
        storer_address = data.get("storer_public_address")
        storer = user_dao.get_user_by_public_address_claim(storer_address, UserRoleType.Storer)
        if not storer:
            return jsonify({"status": "failed", "message": "Storer not found"})
        storer = storer[0]
        
        # Validate and extract rating data
        rated_by = collector_address
        rate = int(data.get("rate"))
        description = data.get("description")

        # Validate rating data
        if not (1 <= rate <= 5):
            return jsonify({"status": "failed", "message": "Invalid rating value"})

        # Create the rating object
        rating = {
            "rated_by": rated_by,
            "rate": rate,
            "description": description
        }

        # Update the storer's ratings
        if "ratings" not in storer:
            storer["ratings"] = []
        storer["ratings"].append(rating)

        # Save the updated storer profile with the new rating
        user_dao.update_doc(storer['_id'],storer)

        return jsonify({'status': 'success'}), 200

    except Exception as e:
        return jsonify({"status": "failed", "error": str(e)}), 500

@authentication_routes.route("/api/v1/user/set_recycler_rating", methods=["POST"])
@jwt_required()
def recycler_rating():
    try:
        data = json.loads(request.data)
        public_address = get_jwt_identity()
        # Check if the storer exists and has the 'storer' claim
        recycler_address = data.get("recycler_public_address")
        recycler = user_dao.get_user_by_public_address_claim(recycler_address, UserRoleType.Recycler)
        if not recycler:
            return jsonify({"status": "failed", "message": "Recycler not found"})
        recycler = recycler[0]
        
        # Validate and extract rating data
        rated_by = public_address
        rate = int(data.get("rate"))
        description = data.get("description")

        # Validate rating data
        if not (1 <= rate <= 5):
            return jsonify({"status": "failed", "message": "Invalid rating value"})

        # Create the rating object
        rating = {
            "rated_by": rated_by,
            "rate": rate,
            "description": description
        }

        # Update the storer's ratings
        if "ratings" not in recycler:
            recycler["ratings"] = []
        recycler["ratings"].append(rating)

        # Save the updated storer profile with the new rating
        user_dao.update_doc(recycler['_id'], recycler)

        return jsonify({'status': 'success'}), 200

    except Exception as e:
        return jsonify({"status": "failed", "error": str(e)}), 500

@authentication_routes.route("/api/v1/user/get_ratings/<string:user_id>", methods=["GET"])
@jwt_required()
def get_ratings(storer_id):
    try:
        # Check if the storer exists and has the 'storer' claim
        result = user_dao.get_user_rating(user_id)
        return jsonify(result), 200

    except Exception as e:
        return jsonify({"status": "failed", "error": str(e)}), 500

@authentication_routes.route("/api/v1/user/collector/stat-bar/<string:id>", methods=["GET"])
@jwt_required()
def get_collector_stat_bar(id):
    try:
        # Check if the storer exists and has the 'storer' claim
        collector = user_dao.get_doc_by_id(id)
        if not collector:
            return jsonify({"status": "failed", "message": "User not found"})
        
        public_address = collector.get('public_address')
        reward = rewards_dao.get_total_rewards(public_address)
        incidents = incident_dao.get_by_user_id(id)
        missions = image_metadata_dao.get_missions_by_public_address(public_address)

        information  = {}
        information["reward"] = reward
        information["number_of_incidents"] = len(incidents)
        information["success_rate"] = 100
        information["number_of_missions"] = len(missions)
        return jsonify({'status': 'success', "information": information}), 200
    except Exception as e:
        return jsonify({"status": "failed", "error": str(e)}), 500

@authentication_routes.route("/api/v1/user/storer/stat-bar/<string:id>", methods=["GET"])
@jwt_required()
def get_storer_stat_bar(id):
    try:
        # Check if the storer exists and has the 'storer' claim
        storer = user_dao.get_doc_by_id(id)
        if not storer:
            return jsonify({"status": "failed", "message": "User not found"})
        
        public_address = storer.get('public_address')
        reward = rewards_dao.get_total_rewards(public_address)
        incidents = incident_dao.get_by_user_id(id)
        entity_lists = entity_list_dao.get_entity_lists_by_public_address(public_address)
        missions = []
        amount_of_stored_items = 0
        amount_of_returned_items = 0
        for entity_list in entity_lists:
            amount_of_stored_items += len(entity_list.get('accepted_image_ids') if entity_list.get('accepted_image_ids') else [])
            amount_of_returned_items += len(entity_list.get('rejected_image_ids') if entity_list.get('rejected_image_ids') else [])
            total_entity_list = entity_list.get('entity_ids') + entity_list.get('accepted_image_ids') if entity_list.get('accepted_image_ids') else [] + entity_list.get('rejected_image_ids') if entity_list.get('rejected_image_ids') else []
            for entity_id in total_entity_list:
                metadata = image_metadata_dao.get_doc_by_id(entity_id)
                missions.append(metadata.get('mission_id'))
        missions = set(missions)

        information  = {}
        information["reward"] = reward
        information["number_of_incidents"] = len(incidents)
        information["amount_of_stored_items"] = amount_of_stored_items
        information["amount_of_returned_items"] = amount_of_returned_items
        information["number_of_missions"] = len(missions)
        return jsonify({'status': 'success', "information": information}), 200
    except Exception as e:
        return jsonify({"status": "failed", "error": str(e)}), 500

@authentication_routes.route("/api/v1/user/creator/stat-bar/<string:id>", methods=["GET"])
@jwt_required()
def get_creator_stat_bar(id):
    try:
        # Check if the storer exists and has the 'storer' claim
        creator = user_dao.get_doc_by_id(id)
        if not creator:
            return jsonify({"status": "failed", "message": "User not found"})
        public_address = creator.get('public_address')
        reward = rewards_dao.get_total_rewards(public_address)
        incidents = incident_dao.get_by_user_id(id)
        entity_lists = entity_list_dao.get_all()
        missions = missions_dao.get_missions_by_public_address(public_address)
        amount_of_scanned_items = 0
        amount_of_stored_items = 0
        amount_of_returned_items = 0
        missions_count = 0
        if missions:
            missions_count =  len(missions)
            mission_ids = []
            for mission in missions:
                mission_ids.append(mission.get('_id'))
            for entity_list in entity_lists.get('result'):
                
                entity_ids = entity_list.get('entity_ids') if entity_list.get('entity_ids') else []
                accepted_image_ids = entity_list.get('accepted_image_ids') if entity_list.get('accepted_image_ids') else []
                rejected_image_ids = entity_list.get('rejected_image_ids') if entity_list.get('rejected_image_ids') else []
                
                for entity_id in entity_ids:
                    metadata = image_metadata_dao.get_doc_by_id(entity_id)
                    if metadata.get('mission_id') in mission_ids:
                        amount_of_scanned_items += 1
                for accepted_image_id in accepted_image_ids:
                    metadata = image_metadata_dao.get_doc_by_id(accepted_image_id)
                    if metadata.get('mission_id') in mission_ids:
                        amount_of_stored_items += 1
                for rejected_image_id in rejected_image_ids:
                    metadata = image_metadata_dao.get_doc_by_id(rejected_image_id)
                    if metadata.get('mission_id') in mission_ids:
                        amount_of_returned_items += 1
        information  = {}
        information["reward"] = reward
        information["number_of_incidents"] = len(incidents)
        information["amount_of_scanned_items"] = amount_of_scanned_items
        information["amount_of_stored_items"] = amount_of_stored_items
        information["amount_of_returned_items"] = amount_of_returned_items
        information["number_of_missions"] = missions_count
        return jsonify({'status': 'success', "information": information}), 200
    except Exception as e:
        return jsonify({"status": "failed", "error": str(e)}), 500
      
@authentication_routes.route("/api/v1/get-all-storers/<string:creator_id>", methods=["GET"])
@jwt_required()
# @requires_user_role(UserRoleType.Recyclium_Admin)
def get_all_storers(creator_id):
    roles = [UserRoleType(r) for r in get_jwt()['roles']]
    user = user_dao.get_doc_by_id(creator_id)
    public_address = user.get('public_address')
    bounties = bounty_dao.get_bounties_by_user(public_address, roles)
    metadata_ids = []
    for bounty in bounties:
        bounty_id = bounty.get('_id')
        metadata = image_metadata_dao.get_metadata_by_bounty_id(bounty_id)
        metadata_ids.extend(metadata)
    storer_list = []
    for metadata_id in metadata_ids:
        entity_lists = entity_list_dao.get_entity_lists_by_entity_id(metadata_id.get('_id'))
        for entity_list in entity_lists:
            storer_list.append(entity_list.get('public_address'))
    storer_list = set(storer_list)
    result = []
    for storer_public_address in storer_list:
        storer = user_dao.get_by_public_address(storer_public_address)
        stored_items = len(entity_list_dao.get_stored_entity_lists_by_public_address(storer_public_address))
        scanned_items = len(entity_list_dao.get_scanned_entity_lists_by_public_address(storer_public_address))
        data = {}
        data["storer_name"] = None
        data["storer_address"] = None
        data["storer_size"] = None
        if 'profile' in storer.get('result')[0]:
            if 'user_name' in storer.get('result')[0]['profile']:
                data["storer_name"] =  storer.get('result')[0]['profile']['user_name']
            if 'address' in storer.get('result')[0]['profile']:
                data["storer_address"] =  storer.get('result')[0]['profile']["address"]
            if 'size' in storer.get('result')[0]['profile']:
                data["storer_size"] =  storer.get('result')[0]['profile']["size"]
        data["stored_items"] = stored_items
        data["storing_items"] = scanned_items - stored_items
        result.append(data)
    return jsonify({'status': 'success', 'storers': result }), 200

@authentication_routes.route("/api/v1/user/collector/stat/<string:id>", methods=["GET"])
def get_collector_stat(id):
    user = user_dao.get_doc_by_id(id)
    public_address = user.get('public_address')
    missions = image_metadata_dao.get_missions_by_public_address(public_address)
    metadata_list = image_metadata_dao.get_metadata_by_public_address(public_address)
    bounties = image_metadata_dao.get_bounties_by_public_address(public_address)
    company_list = []
    for bounty_id in bounties:
        bounty = bounty_dao.get_doc_by_id(bounty_id)
        created_by = bounty.get('created_by')
        company_list.append(created_by)
    company_list = set(company_list)  
    storer_list = []
    for metadata in metadata_list:
        entity_lists = entity_list_dao.get_entity_lists_by_entity_id(metadata.get('_id'))  
        for entity_list in entity_lists:
            storer_list.append(entity_list.get('public_address'))
        
    storer_list = set(storer_list)
    collector_information = {}
    collector_information['number_of_missions'] = len(missions)
    collector_information['amount_of_scanned_items'] = len(metadata_list)
    collector_information['amount_of_companies'] = len(company_list)
    collector_information['amount_of_rewards'] = rewards_dao.get_total_rewards(public_address)
    collector_information['amount_of_storers'] = len(storer_list)
    return jsonify({'status': 'success', 'collector': collector_information })

@authentication_routes.route("/api/v1/user/storer/stat/<string:id>", methods=["GET"])
def get_storer_stat(id):
    user = user_dao.get_doc_by_id(id)
    if not user:
        return jsonify({"status": "failed", "message": "User not found"})
    public_address = user.get('public_address')
    entity_lists = entity_list_dao.get_entity_lists_by_public_address(public_address)
    missions = []
    amount_of_stored_items = 0
    collectors = []
    bounties = []
    for entity_list in entity_lists:
        amount_of_stored_items += len(entity_list.get('entity_ids'))
        for entity_id in entity_list.get('entity_ids'):
            metadata = image_metadata_dao.get_doc_by_id(entity_id)
            missions.append(metadata.get('mission_id'))
            bounties.append(metadata.get('bounty_id'))
            collectors.append(metadata.get('uploaded_by'))
    missions = set(missions)
    collectors = set(collectors)
    bounties = set(bounties)
    average_rating =  None
    ratings = user["ratings"] if "ratings" in user else None

    if ratings:
        total_ratings = sum(rating["rate"] for rating in ratings)
        num_ratings = len(ratings)
        average_rating = total_ratings / num_ratings
        average_rating = max(1, min(5, average_rating))
    
    company_list = []
    for bounty_id in bounties:
        bounty = bounty_dao.get_doc_by_id(bounty_id)
        created_by = bounty.get('created_by')
        company_list.append(created_by)
    company_list = set(company_list)  

    storer_information = {}
    storer_information['number_of_missions'] = len(missions)
    storer_information['amount_of_stored_items'] = amount_of_stored_items
    storer_information['storer_rating'] = average_rating
    storer_information['amount_of_companies'] = len(company_list)
    storer_information['amount_of_rewards'] = rewards_dao.get_total_rewards(public_address)
    storer_information['amount_of_collectors'] = len(collectors)
    return jsonify({'status': 'success', 'storer': storer_information })

@authentication_routes.route("/api/v1/user/get-all-new-storers", methods=["GET"])
@jwt_required()
@requires_user_role(UserRoleType.Recyclium_Admin)
def get_all_new_storers():
    page_size = request.args.get('page_size')
    page =  request.args.get('page')
    page_size = int(page_size) if page_size else 10
    page = int(page)-1 if page else 0
    if page_size < 0 or page < 0 :
        return jsonify({"message": "Pagination parameters are incorrect."}), 400
    new_users = user_dao.get_users_by_status_role( UserStatus.NEW , USER_ROLE["STORER"], page_size, page ) 
    return jsonify({"status": "success", "storers": new_users["result"] }), 200

@authentication_routes.route("/api/v1/user/get-all-new-creators", methods=["GET"])
@jwt_required()
@requires_user_role(UserRoleType.Recyclium_Admin)
def get_all_new_creators():
    page_size = request.args.get('page_size')
    page =  request.args.get('page')
    page_size = int(page_size) if page_size else 10
    page = int(page)-1 if page else 0
    if page_size < 0 or page < 0 :
        return jsonify({"message": "Pagination parameters are incorrect."}), 400
    new_users = user_dao.get_users_by_status_role( UserStatus.NEW , USER_ROLE["CREATOR"], page_size, page ) 
    return jsonify({"status": "success", "creators": new_users["result"] }), 200


@authentication_routes.route("/api/v1/user/get-all-new-recyclers", methods=["GET"])
@jwt_required()
@requires_user_role(UserRoleType.Recyclium_Admin)
def get_all_new_recyclers():
    page_size = request.args.get('page_size')
    page =  request.args.get('page')
    page_size = int(page_size) if page_size else 10
    page = int(page)-1 if page else 0
    if page_size < 0 or page < 0 :
        return jsonify({"message": "Pagination parameters are incorrect."}), 400
    new_users = user_dao.get_users_by_status_role( UserStatus.NEW , USER_ROLE["RECYCLER"], page_size, page ) 
    return jsonify({"status": "success", "recyclers": new_users["result"] }), 200

@authentication_routes.route("/register-recycler", methods=["POST"])
def register_recycler():
    data = request.form
    public_address = canonical_wallet_address(data.get("public_address"))["address"]

    if not public_address:
        resp = jsonify({"message": "Missing parameter `public_address`"})
        return resp, 400

    result = user_dao.get_nonce(public_address)
    if result["status"] == "exists":
        return jsonify({"status": "failed", "message": "already exists"}), 400

    profile = {
        "name": data.get('name'),
        "street": data.get('street'),
        "geocode": {
            "lat": data.get('lat'),
            "lng": data.get('lng'),
        },
        "post_code": data.get('post_code'),
        "city": data.get('city'),
        "country": data.get('country'),
        "description": data.get('description'),
        "accepted_materials": data.get('accepted_materials'),
    }

    referral_id = data.get("referral_id")

    nonce, referrer_public_address = user_dao.register_and_get_nonce_if_not_exists(public_address, referral_id, UserRoleType.Recycler, profile)

    user = user_dao.get_by_public_address(public_address)
    user_id = user['result'][0]['_id']
    UPLOAD_FOLDER = 'verification_document'
    uploaded_file = request.files.get('verification_document')
    dir_path = os.path.join(
            os.path.abspath(os.curdir),
            config["application"]["upload_folder"],
            public_address, UPLOAD_FOLDER
        )
    if not os.path.exists(dir_path):
        os.makedirs(dir_path)

    if uploaded_file:
        filename = secure_filename(uploaded_file.filename)
        filepath = os.path.join(dir_path, filename)

        # Save the uploaded file to the server
        uploaded_file.save(filepath)
        relative_filepath = os.path.join(
            config["application"]["upload_folder"],
            public_address, UPLOAD_FOLDER, filename
        )
        print(filepath)
        # Set the profile image path in the user's database
        user_dao.set_verification_document(user_id, relative_filepath)
    else:
        print('not verification')

    avatar_file = request.files.get('avatar')
    UPLOAD_FOLDER = 'profile_images'
    dir_path = os.path.join(
            os.path.abspath(os.curdir),
            config["application"]["upload_folder"],
            public_address, UPLOAD_FOLDER
        )
    if not os.path.exists(dir_path):
        os.makedirs(dir_path)

    if avatar_file:
        filename = secure_filename(avatar_file.filename)
        filepath = os.path.join(dir_path, filename)

        # Save the uploaded file to the server
        avatar_file.save(filepath)
        relative_filepath = os.path.join(
            config["application"]["upload_folder"],
            public_address, UPLOAD_FOLDER, filename
        )
        # Set the profile image path in the user's database
        user_dao.set_profile_image(user_id, relative_filepath)

    return jsonify({"status": "success", "nonce": nonce}), 200

@authentication_routes.route("/api/v1/user/recycler/profile", methods=["PUT"])
@jwt_required()
def set_recycler_profile():
    data = request.form
    public_address = get_jwt_identity()
    profile = {
        "name": data.get('name'),
        "street": data.get('street'),
        "geocode": {
            "lat": data.get('lat'),
            "lng": data.get('lng'),
        },
        "post_code": data.get('post_code'),
        "city": data.get('city'),
        "country": data.get('country'),
        "description": data.get('description'),
        "accepted_materials": data.get('accepted_materials'),
    }
    user = user_dao.get_by_public_address(public_address)
    user_id = user['result'][0]['_id']
    UPLOAD_FOLDER = 'verification_document'
    uploaded_file = request.files.get('verification_document')
    dir_path = os.path.join(
            os.path.abspath(os.curdir),
            config["application"]["upload_folder"],
            public_address, UPLOAD_FOLDER
        )
    if not os.path.exists(dir_path):
        os.makedirs(dir_path)

    if uploaded_file:
        filename = secure_filename(uploaded_file.filename)
        filepath = os.path.join(dir_path, filename)

        # Save the uploaded file to the server
        uploaded_file.save(filepath)
        relative_filepath = os.path.join(
            os.path.abspath(os.curdir),
            config["application"]["upload_folder"],
            public_address, UPLOAD_FOLDER, filename
        )
        user_dao.set_verification_document(user_id, relative_filepath)
    avatar_file = request.files.get('avatar')
    UPLOAD_FOLDER = 'profile_images'
    dir_path = os.path.join(
            os.path.abspath(os.curdir),
            config["application"]["upload_folder"],
            public_address, UPLOAD_FOLDER
        )
    if not os.path.exists(dir_path):
        os.makedirs(dir_path)

    if avatar_file:
        filename = secure_filename(avatar_file.filename)
        filepath = os.path.join(dir_path, filename)

        # Save the uploaded file to the server
        avatar_file.save(filepath)
        relative_filepath = os.path.join(
            os.path.abspath(os.curdir),
            config["application"]["upload_folder"],
            public_address, UPLOAD_FOLDER, filename
        )
        # Set the profile image path in the user's database
        user_dao.set_profile_image(user_id, relative_filepath)

    return jsonify({"status": "success"}), 200
  
@authentication_routes.route("/api/v1/user/recycler", methods=["GET"])
@jwt_required()
def get_recycler_profile():
    public_address = get_jwt_identity()
    user = user_dao.get_by_public_address(public_address)
    if len(user.get("result")) == 0:
        return jsonify({"status": "faild", "message": "not found user"}), 400

    return jsonify({"status": "success", "profile": user.get("result")[0].get("profile")}), 200

@authentication_routes.route("/api/v1/user/get_recyclers_page_in_category", methods=["GET"])
@jwt_required()
@requires_user_role(UserRoleType.Recyclium_Admin)
def get_recyclers_page_in_category():
    public_address = get_jwt_identity()
    top_recyclers = user_dao.get_all_recyclers(1, 10, 'desc')
    verified_recyclers =  user_dao.get_users_by_status_role_nolimit(UserStatus.VERIFIED, UserRoleType.Recycler)
    new_recyclers =  user_dao.get_users_by_status_role_nolimit(UserStatus.NEW, UserRoleType.Recycler)

    return jsonify({"status": "success", "top_recyclers": top_recyclers, "verified_recyclers": verified_recyclers, "verification_queue_recyclers": new_recyclers}), 200

@authentication_routes.route("/api/v1/user/get_aggregated_data_recycler/<string:user_id>", methods=["GET"])
@requires_user_role(UserRoleType.Recyclium_Admin)
def get_aggregated_data_recycler_detail(user_id):
    c = GetAggregatedDataRecyclerCommand(user_id)
    result = c.execute()
    return jsonify({'status': 'success', 'result': result})

@authentication_routes.route("/api/v1/user/recycler/stat-bar/<string:id>", methods=["GET"])
@jwt_required()
def get_recycler_stat_bar(id):
    try:
        recycler = user_dao.get_doc_by_id(id)
        if not recycler:
            return jsonify({"status": "failed", "message": "User not found"})
        
        public_address = recycler.get('public_address')
        reward = rewards_dao.get_total_rewards(public_address)
        incidents = incident_dao.get_by_user_id(id)
        entity_lists = entity_list_dao.get_entity_lists_by_public_address(public_address)
        missions = []
        amount_of_returned_items = 0
        for entity_list in entity_lists:
            amount_of_returned_items += len(entity_list.get('rejected_image_ids') if entity_list.get('rejected_image_ids') else [])
            total_entity_list = entity_list.get('rejected_image_ids') if entity_list.get('rejected_image_ids') else []
            for entity_id in total_entity_list:
                metadata = image_metadata_dao.get_doc_by_id(entity_id)
                missions.append(metadata.get('mission_id'))
        missions = set(missions)

        information  = {}
        information["reward"] = reward
        information["number_of_incidents"] = len(incidents)
        information["amount_of_returned_items"] = amount_of_returned_items
        information["number_of_missions"] = len(missions)
        return jsonify({'status': 'success', "information": information}), 200
    except Exception as e:
        return jsonify({"status": "failed", "error": str(e)}), 500

@authentication_routes.route("/api/v1/get-all-storers-for-recycler/<string:recycler_id>", methods=["GET"])
@jwt_required()
# @requires_user_role(UserRoleType.Recyclium_Admin)
def get_all_storers_for_recycler(recycler_id):
    roles = [UserRoleType(r) for r in get_jwt()['roles']]
    user = user_dao.get_doc_by_id(recycler_id)
    public_address = user.get('public_address')
    qrcodes = qrcode_dao.get_qrcodes_by_public_address(public_address)
    metadata_ids = []
    for qrcode in qrcodes:
        qrcode_id = qrcode.get('_id')
        metadata = image_metadata_dao.get_metadata_by_qrcode_id(qrcode_id)
        metadata_ids.extend(metadata)
    storer_list = []
    for metadata_id in metadata_ids:
        entity_lists = entity_list_dao.get_entity_lists_by_entity_id(metadata_id.get('_id'))
        for entity_list in entity_lists:
            storer_list.append(entity_list.get('public_address'))
    storer_list = set(storer_list)
    result = []
    for storer_public_address in storer_list:
        storer = user_dao.get_by_public_address(storer_public_address)
        stored_items = len(entity_list_dao.get_stored_entity_lists_by_public_address(storer_public_address))
        scanned_items = len(entity_list_dao.get_scanned_entity_lists_by_public_address(storer_public_address))
        data = {}
        data["storer_name"] = None
        data["storer_address"] = None
        data["storer_size"] = None
        if 'profile' in storer.get('result')[0]:
            if 'user_name' in storer.get('result')[0]['profile']:
                data["storer_name"] =  storer.get('result')[0]['profile']['user_name']
            if 'address' in storer.get('result')[0]['profile']:
                data["storer_address"] =  storer.get('result')[0]['profile']["address"]
            if 'size' in storer.get('result')[0]['profile']:
                data["storer_size"] =  storer.get('result')[0]['profile']["size"]
        data["stored_items"] = stored_items
        data["storing_items"] = scanned_items - stored_items
        result.append(data)
    return jsonify({'status': 'success', 'storers': result }), 200


@authentication_routes.route("/api/v1/get-all-storers-interacted-with-collector/<string:collector_id>", methods=["GET"])
@jwt_required()
# @requires_user_role(UserRoleType.Recyclium_Admin)
def get_all_storers_interacted_with_collector(collector_id):
    user = user_dao.get_doc_by_id(collector_id)
    public_address = user.get('public_address')
    qrcodes = qrcode_dao.get_qrcodes_by_public_address(public_address)
    metadata_ids = []
    for qrcode in qrcodes:
        qrcode_id = qrcode.get('_id')
        metadata = image_metadata_dao.get_metadata_by_qrcode_id(qrcode_id)
        metadata_ids.extend(metadata)
    storer_list = []
    for metadata_id in metadata_ids:
        entity_lists = entity_list_dao.get_entity_lists_by_entity_id(metadata_id.get('_id'))
        for entity_list in entity_lists:
            storer_list.append(entity_list.get('public_address'))
    storer_list = set(storer_list)
    
    return jsonify({'status': 'success', 'storers': storer_list }), 200

@authentication_routes.route("/api/v1/get-all-collectors-interacted-with-storer/<string:storer_id>", methods=["GET"])
@jwt_required()
# @requires_user_role(UserRoleType.Recyclium_Admin)
def get_all_collectors_interacted_with_storer(storer_id):
    user = user_dao.get_doc_by_id(collector_id)
    public_address = user.get('public_address')
    entity_lists = entity_list_dao.get_entity_lists_by_public_address(public_address)
    metadata_list = []
    for entity_list in entity_lists:
        metadata_list = metadata_list + entity_list.get('entity_ids') + entity_list.get('accepted_image_ids') if entity_list.get('accepted_image_ids') else [] + entity_list.get('rejected_image_ids') if entity_list.get('rejected_image_ids') else []
    metadata_list = set(metadata_list)
    qrcode_ids = []
    for metadata in metadata_list:
        qrcode_ids.append(metadata.get('qr_code'))
    qrcode_ids = set(qrcode_ids)
    collectors_publish_address_list = []
    for qrcode_id in qrcode_ids:
        qrcode = qrcode_dao.get_qrcode_by_id(qrcode_id)
        collector_public_address = qrcode.get('public_address')
        collectors_publish_address_list.append(collector_public_address)
    collectors = []
    for collector_public_address in collectors_publish_address_list:
        collector = user_dao.get_by_public_address(collector_public_address)
        collectors.append(collector)
    
    return jsonify({'status': 'success', 'collectors': collectors }), 200
