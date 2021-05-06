from flask import Blueprint, request, jsonify, send_file
import json
import os
import zipfile
from datetime import datetime
from flask_jwt_extended import (jwt_required, get_jwt_identity)
from config import config
from dao.image_metadata_dao import ImageMetadataDao
from utils.get_random_string import get_random_string
from werkzeug.utils import secure_filename
import logging
from security.hashing import hash_image
import shutil
from commands.metadata.query_metadata_command import QueryMetadataCommand
from commands.metadata.add_new_image_command import AddNewImageCommand
from commands.metadata.add_new_metadata_command import AddNewMetadataCommand
from commands.metadata.verify_image_command import VerifyImageCommand

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
    required_params = ["image_id"]
    data = json.loads(request.data)
    public_address = get_jwt_identity()

    if not all(elem in data.keys() for elem in required_params):
        return jsonify(
            {"status": "failed", "message": "Invalid input body. Expected keys :{0}".format(required_params)}), 400

    add_new_metadata_command = AddNewMetadataCommand()
    add_new_metadata_command.input = {
        "public_address": public_address,
        "image_id": data.get("image_id"),
        "tags": data.get("tags"),
        "description": data.get("description", None),
    }
    result = add_new_metadata_command.execute()
    if not add_new_metadata_command.successful:
        return jsonify({'status': 'failed', 'messages': add_new_metadata_command.messages}), 400
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

    public_address = get_jwt_identity()
    if public_address != request_data["uploaded_by"]:
        return jsonify(
            {"status": "failed", "message": "Token owner and `uploaded_by` does not match "}), 400
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
            image_dir = os.path.join(config['application']['upload_folder'], request_data["uploaded_by"])
            os.rename(file_path,
                      os.path.join(image_dir,
                                   doc_id + '-' + filename))

            add_new_image_command1 = AddNewImageCommand()
            add_new_image_command1.input = {
                'public_address': request_data["uploaded_by"],
                'filename': doc_id + '-' + filename,
                'doc_id': doc_id,
                'image_dir': image_dir
            }
            add_new_image_command1.execute()
            if add_new_image_command1.successful:
                resp = jsonify({'message': 'File successfully uploaded', "id": doc_id})
                return resp, 200
            else:
                return jsonify({'status': 'failed', 'messages': add_new_image_command1.messages}), 400
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
                filename_with_docid = doc_id + '-' + file_name
                image_dir = os.path.join(config['application']['upload_folder'], request_data["uploaded_by"])
                os.rename(os.path.join(zip_dir_path, file_name),
                          os.path.join(image_dir, filename_with_docid))

                add_new_image_command1 = AddNewImageCommand()
                add_new_image_command1.input = {
                    'public_address': request_data["uploaded_by"],
                    'filename': filename_with_docid,
                    'doc_id': doc_id,
                    'image_dir': image_dir
                }
                add_new_image_command1.execute()
                if add_new_image_command1.successful:
                    result['success'] = True
                else:
                    result['success'] = False

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


@metadata_routes.route('/api/v1/verify-image', methods=["POST"])
@jwt_required
def verify_image():
    data = json.loads(request.data)
    public_address = get_jwt_identity()

    if data.get('verification'):
        verify_image_c = VerifyImageCommand()
        verify_image_c.input = {
            "public_address": public_address,
            "data": data.get("verification"),
            "image_id": data.get("image_id")
        }
        verify_image_c.execute()
        if not verify_image_c.successful:
            return jsonify({"status": "failed", "messages": ["Error in verification"] + verify_image_c.messages}), 400

    if data.get('annotation'):
        add_annotation = AddNewMetadataCommand()
        add_annotation.input = {
            "public_address": public_address,
            "tags": data["annotation"].get("tags"),
            "description": data["annotation"].get("description"),
            "image_id": data.get('image_id')

        }
        add_annotation.execute()
        if not add_annotation.successful:
            return jsonify({"status": "failed", "messages": ["Error in annotation"] + add_annotation.messages}), 400

    return jsonify({"status": "success"}), 200


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

        if result.get('qr_code_image_path') and os.path.isfile(result.get('qr_code_image_path')):
            return send_file(result.get('qr_code_image_path'))
        elif result.get('image_path') and os.path.isfile(result.get('image_path')):
            return send_file(result.get('image_path'))
        elif os.path.isfile(file_path):
            return send_file(file_path)
        else:
            return jsonify({'status': 'failed', 'error': 'missing_file'}), 400
    else:
        resp = jsonify({'message': 'Missing query parameter: `id`'})
        return resp, 400


@metadata_routes.route('/api/v1/query-metadata', methods=["POST"])
@jwt_required
def query_metadata():
    data = json.loads(request.data)
    required_params = {"status", "fields"}
    public_address = get_jwt_identity()

    if not all(elem in data.keys() for elem in required_params):
        return jsonify(
            {"status": "failed",
             "message": "Invalid input body. Expected query parameters :{0}".format(required_params)}), 400

    page = 1
    if "page" in data:
        try:
            page = int(data["page"])
        except ValueError:
            return jsonify(
                {"status": "failed",
                 "message": "Invalid input body. 'page' is not a number"}), 400

    query_metadata_command = QueryMetadataCommand()
    query_metadata_command.input = {'public_address': public_address, "page": page, "status": data['status'],
                                    'fields': data["fields"]}
    result = query_metadata_command.execute()
    if query_metadata_command.successful:
        return result, 200
    else:
        return jsonify({'status': 'failed', 'messages': query_metadata_command.messages}), 400
