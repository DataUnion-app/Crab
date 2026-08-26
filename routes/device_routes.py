from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from datetime import datetime, timedelta
from collections import defaultdict
import logging
from config import config
from dao.device_dao import device_dao
from dao.rewards_dao import rewards_dao
from dao.metadata_dao import image_metadata_dao
from models.rewards.rewards_model import RewardStatus
from models.metadata.metadata_models import Source

device_routes = Blueprint("device_routes", __name__)

@device_routes.route("/check-status", methods=["POST"])
@jwt_required()
def check_status():
    public_address = get_jwt_identity()
    data = request.get_json()
    device_id = data.get('device_id')

    # Default behavior (True): prevent multiple wallets registering the same device.
    # If set to False, do not block on "device registered to another user".
    enforce_unique_device_registration = config["application"].getboolean(
        "enforce_unique_device_registration",
        fallback=True,
    )

    documents = device_dao.get_device_by_device_id(str(device_id))['result']
    if len(documents) == 0:
        return jsonify({
            'status': 'failed',
            'code': 3,
            'messages': "Device does not exist",
        }), 400

    device = documents[0]
    if not 'public_address' in device:
        return jsonify({
            'status': 'success',
            'code': 1,
            'messages': "Device exists",
        }), 200

    used_by = device['public_address']
    if used_by == None or used_by == '':
        return jsonify({
            'status': 'success',
            'code': 1,
            'messages': "Device exists",
        }), 200
    
    if used_by == public_address:
        return jsonify({
            'status': 'success',
            'code': 2,
            'messages': "Device exists and already registered to this user",
        }), 200
    else:
        if not enforce_unique_device_registration:
            return jsonify({
                'status': 'success',
                'code': 1,
                'messages': "Device exists",
            }), 200
        return jsonify({
            'status': 'failed',
            'code': 4,
            'messages': "Device exists but registered to another user",
        }), 400


@device_routes.route("/register", methods=["POST"])
@jwt_required()
def register():
    public_address = get_jwt_identity()
    data = request.get_json()
    device_id = data.get('device_id')

    # Default behavior (True): prevent multiple wallets registering the same device.
    # If set to False, allow re-registering a device to a different wallet.
    enforce_unique_device_registration = config["application"].getboolean(
        "enforce_unique_device_registration",
        fallback=True,
    )

    documents = device_dao.get_device_by_device_id(str(device_id))['result']
    if len(documents) == 0:
        return jsonify({
            'status': 'failed',
            'code': 3,
            'messages': "Device does not exist",
        }), 400

    device = documents[0]
    if not 'public_address' in device:
        device['public_address'] = public_address
        device_dao.update_doc(device['_id'], device)
        return jsonify({
            'status': 'success',
            'code': 1,
            'messages': "Device registered sucessfully",
        }), 200

    used_by = device['public_address']
    if used_by is None or used_by == '':
        device['public_address'] = public_address
        device_dao.update_doc(device['_id'], device)
        return jsonify({
            'status': 'success',
            'code': 1,
            'messages': "Device registered sucessfully",
        }), 200
    
    if used_by == public_address:
        return jsonify({
            'status': 'success',
            'code': 2,
            'messages': "Device exists and already registered to this user",
        }), 200
    else:
        if not enforce_unique_device_registration:
            # Rebind device to the current user/wallet (anti-multi-wallet protection disabled)
            device['public_address'] = public_address
            device_dao.update_doc(device['_id'], device)
            return jsonify({
                'status': 'success',
                'code': 1,
                'messages': "Device registered sucessfully",
            }), 200
        return jsonify({
            'status': 'failed',
            'code': 4,
            'messages': "Device exists but registered to another user",
        }), 400


@device_routes.route("/get-status/<device_id>", methods=["GET"])
def get_status(device_id):
    documents = device_dao.get_device_by_device_id(str(device_id))['result']
    if len(documents) == 0:
        return jsonify({
            'status': "Device does not exist",
        }), 400

    device = documents[0]
    if not 'public_address' in device:
        return jsonify({
            'status': "Not Registered",
        }), 200

    used_by = device['public_address']
    if used_by == None or used_by == '':
        return jsonify({
            'status': "Not Registered",
        }), 200
    
    return jsonify({
        'status': "Registered",
    }), 200

@device_routes.route("/get-latest-rewards/<device_id>", methods=["GET"])
def get_latest_rewards(device_id):
    documents = device_dao.get_device_by_device_id(str(device_id))['result']
    if len(documents) == 0:
        return jsonify({
            'messages': "Device does not exist",
        }), 400

    public_address = documents[0]['public_address']
    today = datetime.now().strftime('%Y-%m-%d')
    start_key = f'["{public_address}","{today}"]'
    end_key = f'["{public_address}","{today}",{{}}]'
    view_result = image_metadata_dao.query_view_by_key_range("reward-status", "daily-rewards", start_key, end_key, None, 0, 1000000, True)
    rewards = 0
    if len(view_result['rows']) > 0:
        result = view_result['rows'][0]['value']
        if 'rest' in result and result['rest'] > 0:
            rewards += 1
        if 'sleep' in result and result['sleep'] > 0:
            rewards += 2
        if 'exercise' in result:
            exercise_count = 0
            for duration in result['exercise']:
                if exercise_count < 3:
                    if 5 * 60 <= duration < 10 * 60:
                        rewards += 2  # Short exercise (5-10 minutes)
                        exercise_count += 1
                    elif duration >= 10 * 60:
                        rewards += 3  # Long exercise (10+ minutes)
                        exercise_count += 1
    return jsonify({
        'amount': f'{rewards} BEAT',
        'date': f'{today}'
    }), 200

@device_routes.route("/get-all-rewards/<device_id>", methods=["GET"])
def get_all_rewards(device_id):
    documents = device_dao.get_device_by_device_id(str(device_id))['result']
    if len(documents) == 0:
        return jsonify({
            'messages': "Device does not exist",
        }), 400

    public_address = documents[0]['public_address']

    start_key = f'["{public_address}"]'
    end_key = f'["{public_address}",{{}}]'
    view_result = image_metadata_dao.query_view_by_key_range("reward-status", "daily-rewards", start_key, end_key, None, 0, 1000000, True, True)

    total_rewards = {}
    # Initialize a dictionary to hold exercise durations per day
    exercise_durations = {}
    for row in view_result['rows']:
        record_type = row['key'][2]
        value = row['value'][record_type]
        date = row['key'][1]
        public_address = row['key'][0]
        # Initialize date entry if not present in total_rewards
        if date not in total_rewards:
            total_rewards[date] = 0  # Total reward for the day
        # Process rewards based on record_type
        if record_type == 'rest' and value > 0:
            total_rewards[date] += 1  # Cap rest rewards at 1 per day
        elif record_type == 'sleep' and value > 0:
            total_rewards[date] += 2  # Cap sleep rewards at 1 per day
        elif record_type == 'exercise':
            if date not in exercise_durations:
                exercise_durations[date] = []
            exercise_durations[date].append(value[0])

    for date, durations in exercise_durations.items():
        exercise_count = 0
        for duration in durations:
            if exercise_count < 3:
                if 5 * 60 <= duration < 10 * 60:
                    total_rewards[date] += 2  # Short exercise (5-10 minutes)
                    exercise_count += 1
                elif duration >= 10 * 60:
                    total_rewards[date] += 3  # Long exercise (10+ minutes)
                    exercise_count += 1

    result = [{'date': date, 'amount': f'{amount} BEAT'} for date, amount in sorted(total_rewards.items())]

    return jsonify(result), 200
