from flask import Blueprint, render_template, session, abort, request, jsonify
import json
import os
import zipfile
import pandas as pd
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
from models.ImageStatus import ImageStatus

if not config['application'].getboolean('jwt_on'): jwt_required = lambda fn: fn

user = config['couchdb']['user']
password = config['couchdb']['password']
db_host = config['couchdb']['db_host']
metadata_db = config['couchdb']['metadata_db']
imageMetadataDao = ImageMetadataDao()
imageMetadataDao.set_config(user, password, db_host, metadata_db)

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'PNG', 'JPG', 'JPEG', 'GIF'}

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
            data_to_save["type"] = "image"
            data_to_save["status_description"] = ImageStatus.AVAILABLE_FOR_TAGGING.name
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


@metadata_routes.route('/api/v1/bulk/upload-zip', methods=['POST'])
@jwt_required
def upload_zip_file():
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
    if file and '.' in file.filename and file.filename.rsplit('.', 1)[1].lower() in ['zip', 'ZIP']:
        bulk_upload_doc_id = get_random_string()

        zip_filename = secure_filename(file.filename)
        dir_path = os.path.join(config['application']['upload_folder'], request_data["uploaded_by"], 'temp',
                                bulk_upload_doc_id)
        if not os.path.exists(dir_path):
            os.makedirs(dir_path)
        file_path = os.path.join(dir_path, zip_filename)
        file.save(file_path)

        data_to_save = dict({})
        data_to_save["filename"] = zip_filename
        data_to_save["doc_id"] = bulk_upload_doc_id
        data_to_save["uploaded_by"] = request_data["uploaded_by"]
        data_to_save["type"] = "bulk_upload"
        data_to_save["status"] = "new"
        data_to_save["status_description"] = "Zip not verified"
        data_to_save["uploaded_at"] = datetime.timestamp(datetime.now())

        # Save metadata
        bulk_upload_doc_id = imageMetadataDao.save(bulk_upload_doc_id, data_to_save)["id"]

        with zipfile.ZipFile(file_path, 'r') as zip_ref:
            zip_ref.extractall(dir_path)

        file_list = [file for file in os.listdir(dir_path) if allowed_file(file)]

        bulk_upload_result = []
        for file_name in file_list:

            result = dict({'file_name': file_name})

            f_path = os.path.join(dir_path, file_name)
            doc_id = str(hash_image(f_path))

            # Check if it exists in the database already
            image_exists = imageMetadataDao.exists(doc_id)

            # File does not exist yet
            if not image_exists:
                # Save file
                data_to_save = dict({})
                data_to_save["filename"] = file_name
                data_to_save["uploaded_by"] = request_data["uploaded_by"]
                data_to_save["status"] = ImageStatus.AVAILABLE_FOR_TAGGING.name
                data_to_save["hash"] = bulk_upload_doc_id
                data_to_save["type"] = "image"
                data_to_save["bulk_upload_id"] = bulk_upload_doc_id
                data_to_save["status_description"] = "Image not verified"
                data_to_save["uploaded_at"] = datetime.timestamp(datetime.now())

                os.rename(os.path.join(dir_path, file_name),
                          os.path.join(config['application']['upload_folder'], request_data["uploaded_by"],
                                       doc_id + '-' + file_name))

                # Save metadata
                doc_id = imageMetadataDao.save(doc_id, data_to_save)["id"]
                result['success'] = True
                result['doc_id'] = doc_id

            else:
                result['success'] = False
                result['message'] = 'already_exists'
                logging.debug(
                    "Not allowing address [{}] to upload image [{}].".format(request_data["uploaded_by"],
                                                                             doc_id))

            bulk_upload_result.append(result)

        resp = jsonify(
            {'message': 'File successfully uploaded', "id": bulk_upload_doc_id, 'result': bulk_upload_result})
        return resp, 200
    else:
        logging.debug(
            "Not allowing address [{}] to upload image.".format(request_data["uploaded_by"]))
        resp = jsonify({'message': 'Zip upload failed'})
        return resp, 400


@metadata_routes.route('/api/v1/metadata', methods=["GET"])
@jwt_required
def get_metadata_by_eth_address():
    args = request.args
    if "eth_address" in args:
        eth_address = args["eth_address"]
        result = imageMetadataDao.get_metadata_by_eth_address(eth_address=eth_address, status=args.get("eth_address"))
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

    all_data = imageMetadataDao.getAll()['result']
    all_data = [row for row in all_data if row.get('type') == "image" and
                row.get('status') in [ImageStatus.AVAILABLE_FOR_TAGGING.name, ImageStatus.VERIFIED.name]]

    data = dict({})
    for row in all_data:
        data[row['_id']] = {'time': datetime.fromtimestamp(row['uploaded_at']).strftime('%Y-%m-%d %H:%M:%S'),
                            'tags': []}
        tags_set = set()
        tag_data = row.get('tag_data')
        if tag_data:
            for tags in tag_data:
                for tag in tags['tags']:
                    tags_set.add(tag)
            data[row['_id']]['tags'] = tags_set
    d = pd.DataFrame.from_dict(data, orient='index')
    d['time'] = pd.to_datetime(d['time'])
    groups = d.groupby(pd.Grouper(key='time', freq='D'))
    total_summary = []
    for key, group in groups:
        summary = dict({})
        summary['time'] = key.timestamp()
        summary['num_images'] = 0
        summary['tags'] = []
        for row_index, row in group.iterrows():
            summary['num_images'] = summary['num_images'] + 1
            for tag in row['tags']:
                present = False
                for index, s in enumerate(summary['tags']):
                    if s.get('name') == tag:
                        present = True
                        summary['tags'][index]['value'] = summary['tags'][index]['value'] + 1
                if not present:
                    value = {"name": tag, "value": 1}
                    summary['tags'].append(value)
        total_summary.append(summary)

    result = dict({
        "initial_images": len(all_data),
        "data": total_summary
    })

    response = jsonify(result)
    return response, 200
