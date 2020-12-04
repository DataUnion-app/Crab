from flask import Flask, jsonify, request
import json
import configparser
from models import NewImageMetadata
from dao.ImageMetadataDao import ImageMetadataDao
from utils.get_random_string import get_random_string

config = configparser.ConfigParser()
config.read('properties.ini')

app = Flask(__name__)

# ImageMetadataDao.set_config(user=config['couchdb']['user'],password=config['couchdb']['password'],
#                             db_host=config['couchdb']['db_host'],db_name='test')
user=config['couchdb']['user']
password=config['couchdb']['password']
db_host=config['couchdb']['db_host']
imageMetadataDao = ImageMetadataDao()
imageMetadataDao.set_config(user,password,db_host,'test')

@app.route('/version')
def version():
    return "Version: {0}".format(config['application']['version'])

@app.route('/api/v1/upload', methods = ["POST"])
def upload_image():

    data = json.loads(request.data)
    doc_id = get_random_string()

    if not data.get("uploaded_by") or not data.get("timestamp"):
        return jsonify({"status": "failed", "message": "Missing parameters"}), 400

    # TODO: Save the document in db
    imageMetadataDao.save(doc_id, data)
    return jsonify({"status": "success"}), 200

@app.route('/api/v1/all-metadata', methods = ["GET"])
def get_all_image_metadata():
    result = imageMetadataDao.getAll()
    return  result

if __name__ == '__main__':
    app.run(port=config['application']['port'])
