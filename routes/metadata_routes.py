from flask import Blueprint, request, jsonify, send_file
import json
import os
import zipfile
import pandas as pd
from datetime import datetime
from flask_jwt_extended import (jwt_required, get_jwt_identity)
from config import config
from dao.ImageMetadataDao import ImageMetadataDao
from utils.get_random_string import get_random_string
from werkzeug.utils import secure_filename
import logging
from security.hashing import hash_image
from models.ImageStatus import ImageStatus
import shutil
from commands.metadata.query_metadata_command import QueryMetadataCommand
from commands.metadata.add_new_metadata_command import AddNewMetadataCommand
from commands.metadata.my_stats_command import MyStatsCommand

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
    required_params = ["timestamp", "other", "photo_id", "tags"]
    data = json.loads(request.data)
    public_address = get_jwt_identity()

    if not all(elem in data.keys() for elem in required_params):
        return jsonify(
            {"status": "failed", "message": "Invalid input body. Expected keys :{0}".format(required_params)}), 400

    add_new_metadata_command = AddNewMetadataCommand()
    add_new_metadata_command.input = {
        "public_address": public_address,
        "photo_id": data.get("photo_id"),
        "tags": data.get("tags"),
        "description": data.get("description", None),
        "other": data.get("other")
    }
    result = add_new_metadata_command.execute()
    return jsonify(result), 200


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

        dir_path = os.path.join(config['application']['upload_folder'], request_data["uploaded_by"], 'temp')
        if not os.path.exists(dir_path):
            os.makedirs(dir_path)
        filename = secure_filename(file.filename)
        file_path = os.path.join(dir_path, filename)
        file.save(file_path)

        # Compute image hash value
        doc_id = str(hash_image(file_path))

        # Check if it exists in the database already
        image_exists = imageMetadataDao.exists(doc_id)

        # File does not exist yet
        if not image_exists:
            # Save file
            os.rename(file_path,
                      os.path.join(config['application']['upload_folder'], request_data["uploaded_by"],
                                   doc_id + '-' + filename))
            data_to_save = dict({})
            data_to_save["filename"] = doc_id + '-' + filename
            data_to_save["uploaded_by"] = request_data["uploaded_by"]
            data_to_save["status"] = "new"
            data_to_save["hash"] = doc_id
            data_to_save["type"] = "image"
            data_to_save["extension"] = filename.split('.')[-1]
            data_to_save["status_description"] = ImageStatus.AVAILABLE_FOR_TAGGING.name
            data_to_save["uploaded_at"] = datetime.timestamp(datetime.now())

            # Save metadata
            doc_id = imageMetadataDao.save(doc_id, data_to_save)["id"]

            resp = jsonify({'message': 'File successfully uploaded', "id": doc_id})
            return resp, 200
        else:
            os.remove(file_path)
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

    response = None
    if file and '.' in file.filename and file.filename.rsplit('.', 1)[1].lower() in ['zip', 'ZIP']:
        bulk_upload_doc_id = get_random_string()

        zip_filename = secure_filename(file.filename)
        zip_dir_path = os.path.join(config['application']['upload_folder'], request_data["uploaded_by"], 'temp',
                                    bulk_upload_doc_id)
        if not os.path.exists(zip_dir_path):
            os.makedirs(zip_dir_path)
        zip_file_path = os.path.join(zip_dir_path, zip_filename)
        file.save(zip_file_path)

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

        with zipfile.ZipFile(zip_file_path, 'r') as zip_ref:
            zip_ref.extractall(zip_dir_path)

        file_list = [file for file in os.listdir(zip_dir_path) if allowed_file(file)]

        bulk_upload_result = []
        for file_name in file_list:

            result = dict({'file_name': file_name})

            f_path = os.path.join(zip_dir_path, file_name)
            doc_id = str(hash_image(f_path))
            result['doc_id'] = doc_id

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

                os.rename(os.path.join(zip_dir_path, file_name),
                          os.path.join(config['application']['upload_folder'], request_data["uploaded_by"],
                                       doc_id + '-' + file_name))

                # Save metadata
                doc_id = imageMetadataDao.save(doc_id, data_to_save)["id"]
                result['success'] = True

            else:
                result['success'] = False
                result['message'] = 'already_exists'
                logging.debug(
                    "Not allowing address [{}] to upload image [{}].".format(request_data["uploaded_by"],
                                                                             doc_id))

            bulk_upload_result.append(result)

        response = jsonify(
            {'message': 'File successfully uploaded', "id": bulk_upload_doc_id, 'result': bulk_upload_result})
    else:
        logging.debug(
            "Not allowing address [{}] to upload image.".format(request_data["uploaded_by"]))
        response = jsonify({'message': 'Zip upload failed'})

    shutil.rmtree(zip_dir_path)
    return response


@metadata_routes.route('/api/v1/my-metadata', methods=["GET"])
@jwt_required
def get_userdata():
    """
    This api is used to get all the image ids and tags for the user. A user can access only his own data.

    Args:
        page (optional): Default: 1 - 100, page no. 2 -> 101 - 200

    Returns:
        Returns the object containing list of image ids and tags for the image that user has added.
        e.g.
        {page: 1, result: [{ photo_id: "", page_size: 100}]

    Raises:
        None.
    """
    args = request.args
    page = 1
    if "page" in args:
        page = int(args["page"])

    public_address = get_jwt_identity()

    result = imageMetadataDao.get_metadata_by_address(public_address, page)
    return result


@metadata_routes.route('/api/v1/my-images', methods=["GET"])
@jwt_required
def get_metadata_by_eth_address():
    """
        This api is used to get all the image ids uploaded by a user. A user can access only his own images.

        Args:
            page (optional): Default: 1 - 100, page no. 2 -> 101 - 200

        Returns:
            Returns the object containing list of image ids and tags for the image that user has added.
            e.g.
            {page: 1, result: [{ photo_id: "", tags :["xyz","abc"]}], page_size: 100}

        Raises:
            None.
    """
    args = request.args
    page = 1
    if "page" in args:
        page = int(args["page"])

    public_address = get_jwt_identity()
    fields = ["filename", "hash", "type", "uploaded_at"]
    result = imageMetadataDao.get_images_by_eth_address(eth_address=public_address, page=page, fields=fields)
    return result, 200


@metadata_routes.route('/api/v1/report-images', methods=["POST"])
@jwt_required
def report_images():
    required_params = {"photos"}
    try:
        data = json.loads(request.data)
        public_address = get_jwt_identity()

        if required_params != set(data.keys()):
            return jsonify(
                {"status": "failed", "message": "Invalid input body. Expected keys :{0}".format(required_params)}), 400
        if not isinstance(data["photos"], list):
            return jsonify(
                {"status": "failed", "message": "Invalid input body. Expected `photos` to be a list"}), 400

        imageMetadataDao.marked_as_reported(public_address, data["photos"])
        return jsonify({"status": "success"}), 200

    except ValueError as e:
        return jsonify(
            {"status": "failed", "message": "Invalid input body."}), 400


@metadata_routes.route('/api/v1/get-image-by-id', methods=["GET"])
@jwt_required
def get_image():
    args = request.args
    if "id" in args:
        doc_id = args["id"]
        result = imageMetadataDao.get_doc_by_id(doc_id)
        if result.get("error"):
            resp = jsonify({'status': 'failed', 'error': result.get('error')})
            return resp, 400

        file_name = result["filename"]
        file_path = os.path.join(config['application']['upload_folder'],
                                 result["uploaded_by"],
                                 file_name)

        if os.path.isfile(file_path):
            return send_file(file_path)
        else:
            return jsonify({'status': 'failed', 'error': 'missing_file'}), 400
    else:
        resp = jsonify({'message': 'Missing query parameter: `id`'})
        return resp, 400


@metadata_routes.route('/api/v1/query-metadata', methods=["GET"])
@jwt_required
def query_metadata():
    args = request.args
    required_params = {"status", "skip_tagged"}
    public_address = get_jwt_identity()

    if required_params != set(args.keys()):
        return jsonify(
            {"status": "failed",
             "message": "Invalid input body. Expected query parameters :{0}".format(required_params)}), 400

    page = 1
    if "page" in args:
        page = int(args["page"])

    query_metadata_command = QueryMetadataCommand()
    query_metadata_command.input = {'public_address': public_address, "page": page, "status": args['status'],
                                    'skip_tagged': args['skip_tagged']}
    result = query_metadata_command.execute()
    return result, 200


@metadata_routes.route('/api/v1/stats', methods=["GET"])
def get_stats():
    all_data = imageMetadataDao.getAll()['result']
    all_data = [row for row in all_data if row.get('type') == "image" and
                row.get('status') in [ImageStatus.AVAILABLE_FOR_TAGGING.name, ImageStatus.VERIFIED.name]]

    data = dict({})

    if len(all_data) == 0:
        result = dict({
            "initial_images": 0,
            "data": []
        })
        response = jsonify(result)
        return response, 200

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


@metadata_routes.route('/api/v1/my-stats', methods=["GET"])
@jwt_required
def get_my_stats():
    args = request.args
    required_params = {'start_time', 'end_time'}
    public_address = get_jwt_identity()
    if not all(elem in args.keys() for elem in required_params):
        return jsonify(
            {"status": "failed",
             "message": "Invalid input body. Expected query parameters :{0}".format(required_params)}), 400
    my_stats_command = MyStatsCommand()
    try:
        my_stats_command.input = {
            'public_address': public_address,
            'group_by': int(args.get('group_by', 24)),
            'start_time': float(args['start_time']),
            'end_time': float(args['end_time'])
        }
        response = my_stats_command.execute()
    except ValueError:
        return jsonify({"status": "failed", "messages": ["Value error: Please check if input is correct"]}), 400
    except:
        return jsonify({"status": "failed", "messages": ["Please contact support team."]}), 400

    return response, 200
