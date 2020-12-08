from flask import Flask, jsonify, request, send_file
import json
import os
from datetime import datetime
from models import NewImageMetadata
from flask_jwt_extended import (create_access_token, create_refresh_token, jwt_required, jwt_refresh_token_required,
                                get_jwt_identity, get_raw_jwt)
from flask_jwt_extended import JWTManager
from authentication_routes import authentication_routes
from metadata_routes import metadata_routes
from config import config


app = Flask(__name__)

app.register_blueprint(authentication_routes)
app.register_blueprint(metadata_routes)

app.secret_key = config['application']['secret_key']
app.config['UPLOAD_FOLDER'] = config['application']['upload_folder']
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024
app.config['JWT_SECRET_KEY'] = config['application']['jwt_secret_string']
jwt = JWTManager(app)



@app.route('/version')
def version():
    return "Version: {0}".format(config['application']['version'])


if __name__ == '__main__':
    app.run(port=config['application']['port'])
