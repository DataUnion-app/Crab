from flask import Blueprint, render_template, session, abort, request, jsonify
import json
import os
from datetime import datetime
from dao.users_dao import UsersDao
from flask_jwt_extended import (create_access_token, create_refresh_token, jwt_required, jwt_refresh_token_required,
                                get_jwt_identity, get_raw_jwt)
from config import config
from dao.ImageMetadataDao import ImageMetadataDao
from utils.get_random_string import get_random_string
from werkzeug.utils import secure_filename
import logging
from security.hashing import hash_image

if not config['application'].getboolean('jwt_on'): jwt_required = lambda fn: fn

user = config['couchdb']['user']
password = config['couchdb']['password']
db_host = config['couchdb']['db_host']
metadata_db = config['couchdb']['metadata_db']
imageMetadataDao = ImageMetadataDao()
imageMetadataDao.set_config(user, password, db_host, metadata_db)

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}

metadata_routes = Blueprint('metadata_routes', __name__)


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


@metadata_routes.route('/api/v1/upload', methods=["POST"])
@jwt_required
def upload_metadata():
    required_params = {"timestamp", "other", "photo_id", "tags"}
    data = json.loads(request.data)
    public_address = get_jwt_identity()

    if required_params != set(data.keys()):
        return jsonify(
            {"status": "failed", "message": "Invalid input body. Expected keys :{0}".format(required_params)}), 400

    imageMetadataDao.add_metadata_for_image(public_address, data["photo_id"], data["tags"], data["other"])
    return jsonify({"status": "success"}), 200


@metadata_routes.route('/api/v1/all-metadata', methods=["GET"])
@jwt_required
def get_all_image_metadata():
    result = imageMetadataDao.get_all_verified_metadata()
    return result


@metadata_routes.route('/api/v1/upload-file', methods=['POST'])
@jwt_required
def upload_file():
    # Validate if request is correct
    required_params = {"uploaded_by"}
    request_data = request.form
    if required_params != set(request_data.keys()):
        return jsonify(
            {"status": "failed", "message": "Invalid input body. Expected keys :{0}".format(required_params)}), 400

    if 'file' not in request.files:
        resp = jsonify({'message': 'No file part in the request'})
        resp.status_code = 400
        return resp
    file = request.files['file']
    if file.filename == '':
        resp = jsonify({'message': 'No file selected for uploading'})
        return resp, 400
    if file and allowed_file(file.filename):
        # Compute image hash value
        doc_id = str(hash_image(file))

        # Check if it exists in the database already
        image_exists = imageMetadataDao.exists(doc_id)

        # File does not exist yet
        if not image_exists:
            # Save file
            filename = secure_filename(doc_id + '-' + file.filename)
            dir_path = os.path.join(config['application']['upload_folder'], request_data["uploaded_by"])
            if not os.path.exists(dir_path):
                os.makedirs(dir_path)
            file_path = os.path.join(dir_path, filename)
            file.save(file_path)

            data_to_save = dict({})
            data_to_save["filename"] = filename
            data_to_save["uploaded_by"] = request_data["uploaded_by"]
            data_to_save["status"] = "new"
            data_to_save["hash"] = doc_id
            data_to_save["status_description"] = "Image not verified"
            data_to_save["uploaded_at"] = datetime.timestamp(datetime.now())

            # Save metadata
            doc_id = imageMetadataDao.save(doc_id, data_to_save)["id"]

            resp = jsonify({'message': 'File successfully uploaded', "id": doc_id})
            return resp, 200
        else:
            logging.debug(
                "Not allowing address [{}] to upload image [{}].".format(request_data["uploaded_by"], doc_id))
            resp = jsonify({'message': 'The uploaded file already exists in the dataset.'})
            return resp, 400
    else:
        logging.debug(
            "Not allowing address [{}] to upload file as type not supported.".format(request_data["uploaded_by"]))
        resp = jsonify({'message': 'Allowed file types are {0}'.format(ALLOWED_EXTENSIONS)})
        return resp, 400


@metadata_routes.route('/api/v1/metadata', methods=["GET"])
@jwt_required
def get_metadata_by_eth_address():
    args = request.args
    if "eth_address" in args:
        eth_address = args["eth_address"]
        result = imageMetadataDao.get_metadata_by_eth_address(eth_address)
        return result, 200
    else:
        resp = jsonify({'message': 'Missing query parameter: `eth_address`'})
        return resp, 400


@metadata_routes.route('/api/v1/get_image', methods=["GET"])
@jwt_required
def get_image():
    args = request.args
    if "id" in args:
        doc_id = args["id"]
        result = imageMetadataDao.get_doc_by_id(doc_id)
        if not result.get("error") and len(result["result"]) != 1:
            resp = jsonify({'message': 'Data not found'})
            return resp, 400

        file_name = result["result"][0]["filename"]
        file_path = os.path.join(app.config['UPLOAD_FOLDER'],
                                 result["result"][0]["uploaded_by"],
                                 file_name)
        return send_file(file_path)

    else:
        resp = jsonify({'message': 'Missing query parameter: `id`'})
        return resp, 400


@metadata_routes.route('/api/v1/stats', methods=["GET"])
def get_stats():
    # TODO: Fetch data from database
    result = {
        "initial_images": 100,
        "data": [
            {"time": 1606923074, "num_images": 5, "dog": 5, "outside": 3, "daylight": 2},
            {"time": 1606923075, "num_images": 2, "dog": 2, "outside": 1},
            {"time": 1606923076, "num_images": 10, "dog": 8, "outside": 3, "daylight": 7, "horse": 2},
            {"time": 1606923077, "num_images": 3, "dog": 1, "outside": 3, "daylight": 3, "horse": 2},
            {"time": 1606923078, "num_images": 1, "dog": 1, "daylight": 1},
            {"time": 1606923079, "num_images": 12, "dog": 8, "outside": 12, "daylight": 12, "horse": 4}
        ]
    }
    response = jsonify(result)
    return response, 200
