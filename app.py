from flask import Flask, jsonify, request, send_file
import json
import os
from datetime import datetime
from models import NewImageMetadata
from flask_jwt_extended import (create_access_token, create_refresh_token, jwt_required, jwt_refresh_token_required,
                                get_jwt_identity, get_raw_jwt)
from flask_jwt_extended import JWTManager
import logging
from authentication_routes import authentication_routes, sessions_dao
from metadata_routes import metadata_routes
from config import config
from dao.sessions_dao import SessionsDao

if not config['application'].getboolean('jwt_on'): jwt_required = lambda fn: fn

logging.basicConfig(format='%(asctime)s %(levelname)s:%(message)s',
                    filename='logs/{}'.format(config["logging"]["file_name"]),
                    level=config["logging"].getint('level'))

app = Flask(__name__)

app.register_blueprint(authentication_routes)
app.register_blueprint(metadata_routes)

app.secret_key = config['application']['secret_key']
app.config['UPLOAD_FOLDER'] = config['application']['upload_folder']
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024
app.config['JWT_SECRET_KEY'] = config['application']['jwt_secret_string']
app.config['JWT_BLACKLIST_ENABLED'] = True
app.config['JWT_BLACKLIST_TOKEN_CHECKS'] = ['access']

jwt = JWTManager(app)


@jwt.token_in_blacklist_loader
def check_if_token_in_blacklist(decrypted_token):
    jti = decrypted_token['jti']
    return sessions_dao.is_blacklisted(jti)


@app.route('/version')
def version():
    return "Version: {0}".format(config['application']['version'])


@app.route('/', methods=["GET"])
def api():
    return send_file(os.path.join('public', 'api.html'))


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=config['application']['port'])
