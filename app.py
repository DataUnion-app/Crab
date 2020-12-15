from flask import Flask, send_file
import os
from flask_jwt_extended import JWTManager
import logging
from logging.handlers import TimedRotatingFileHandler
from routes.authentication_routes import authentication_routes, sessions_dao
from routes.metadata_routes import metadata_routes
from config import config

if not config['application'].getboolean('jwt_on'): jwt_required = lambda fn: fn

handler = TimedRotatingFileHandler(filename='logs/{}'.format(config["logging"]["file_name"]), when="D", interval=1)

logging.basicConfig(format='%(asctime)s %(levelname)s:%(message)s', level=config["logging"].getint('level'),
                    handlers=[handler])

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
