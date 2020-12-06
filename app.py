from flask import Flask, jsonify, request, send_file
import json
import configparser
from werkzeug.utils import secure_filename
import os
from datetime import datetime
from models import NewImageMetadata
from dao.ImageMetadataDao import ImageMetadataDao
from utils.get_random_string import get_random_string

config = configparser.ConfigParser()
config.read('properties.ini')

ALLOWED_EXTENSIONS = set(['png', 'jpg', 'jpeg', 'gif'])
UPLOAD_FOLDER = 'data'

app = Flask(__name__)
app.secret_key = "secret key"
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024

user = config['couchdb']['user']
password = config['couchdb']['password']
db_host = config['couchdb']['db_host']
metadata_db = config['couchdb']['metadata_db']
imageMetadataDao = ImageMetadataDao()
imageMetadataDao.set_config(user, password, db_host, metadata_db)


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


@app.route('/version')
def version():
    return "Version: {0}".format(config['application']['version'])


@app.route('/api/v1/upload', methods=["POST"])
def upload_metadata():
    required_params = set(["timestamp", "other", "photo_id", "tags"])
    data = json.loads(request.data)
    if required_params != set(data.keys()):
        return jsonify(
            {"status": "failed", "message": "Invalid input body. Expected keys :{0}".format(required_params)}), 400


    imageMetadataDao.add_metadata_for_image(data["photo_id"], data["tags"], data["other"])
    return jsonify({"status": "success"}), 200


@app.route('/api/v1/all-metadata', methods=["GET"])
def get_all_image_metadata():
    result = imageMetadataDao.getAll()
    return result


@app.route('/api/v1/upload-file', methods=['POST'])
def upload_file():
    # Validate if request is correct
    required_params = set(["uploaded_by"])
    data = request.form
    if required_params != set(data.keys()):
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
        doc_id = get_random_string()

        # Save file
        filename = secure_filename(doc_id + '-' + file.filename)
        dir_path = os.path.join(app.config['UPLOAD_FOLDER'], data["uploaded_by"])
        if not os.path.exists(dir_path):
            os.makedirs(dir_path)
        file_path = os.path.join(dir_path, filename)
        file.save(file_path)

        data_to_save = dict(data)
        data_to_save["filename"] = filename
        data_to_save["status"] = "new"
        data_to_save["status_description"] = "Image not verified"
        data_to_save["uploaded_at"] =  datetime.timestamp(datetime.now())

        # Save metadata
        doc_id = imageMetadataDao.save(doc_id, data_to_save)["id"]

        resp = jsonify({'message': 'File successfully uploaded', "id": doc_id})
        return resp, 200

    else:
        resp = jsonify({'message': 'Allowed file types are {0}'.format(ALLOWED_EXTENSIONS)})
        return resp, 400


@app.route('/api/v1/metadata', methods=["GET"])
def get_metadata_by_eth_address():
    args = request.args
    if "eth_address" in args:
        eth_Address = args["eth_address"]
        result = imageMetadataDao.get_metadata_by_eth_address(eth_Address)
        return result, 200
    else:
        resp = jsonify({'message': 'Missing query paramerter: `eth_address`'})
        return resp, 400


@app.route('/api/v1/get_image', methods=["GET"])
def get_image():
    args = request.args
    if "id" in args:
        doc_id = args["id"]
        result = imageMetadataDao.get_doc_by_id(doc_id)
        if len(result["result"]) != 1:
            resp = jsonify({'message': 'Data not found'})
            return resp, 400

        file_name = result["result"][0]["filename"]
        file_path = os.path.join(app.config['UPLOAD_FOLDER'],
                                 result["result"][0]["uploaded_by"],
                                 result["result"][0]["filename"])
        return send_file(file_path)

    else:
        resp = jsonify({'message': 'Missing query paramerter: `id`'})
        return resp, 400


@app.route('/api/v1/stats', methods=["GET"])
def get_stats():
    args = request.args

    # TODO: Fetch data from database
    result = {
        "initial_images": 100,
        "data": [
            {"time": 1606923074, "num_images": 5, "tags": [{"dog": 5}, {"outside": 3}, {"daylight": 2}]},
            {"time": 1606923075, "num_images": 2, "tags": [{"dog": 2}, {"outside": 1}]},
            {"time": 1606923076, "num_images": 10, "tags": [{"dog": 8}, {"outside": 3}, {"daylight": 7},
                                                            {"horse": 2}]},
            {"time": 1606923077, "num_images": 3, "tags": [{"dog": 1}, {"outside": 3}, {"daylight": 3},
                                                           {"horse": 2}]},
            {"time": 1606923078, "num_images": 1, "tags": [{"dog": 1}, {"daylight": 1}]},
            {"time": 1606923079, "num_images": 12, "tags": [{"dog": 8}, {"outside": 12}, {"daylight": 12},
                                                            {"horse": 4}]}
        ]
    }
    response = jsonify(result)
    return response, 200


if __name__ == '__main__':
    app.run(port=config['application']['port'])
