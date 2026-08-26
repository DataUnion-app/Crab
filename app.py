import os
import logging
import sys
from datetime import timedelta
from http.client import HTTPException
from logging.handlers import TimedRotatingFileHandler
from routes.mission_routes import mission_routes
from utils.get_project_dir import get_project_root

from config import config
from flask import Flask, send_from_directory

log_filename = os.path.join(get_project_root(), 'logs', config["logging"]["file_name"])
handler = TimedRotatingFileHandler(filename=log_filename, when="D", interval=1)
logging.basicConfig(
    format="%(asctime)s %(levelname)s:%(message)s",
    level=config["logging"].getint("level"),
    handlers=[handler],
)


def my_handler(type, value, tb):
    logging.exception("Uncaught exception: {0}".format(str(value)))


# Install exception handler
sys.excepthook = my_handler

from flask import Flask, send_file, jsonify, render_template
from flask_jwt_extended import JWTManager
from flask_cors import CORS
from flask_caching import Cache
from routes.authentication_routes import authentication_routes, sessions_dao
from routes.metadata_routes import metadata_routes
from routes.staticdata import staticdata_routes
from routes.taxonomy import taxonomy_routes
from routes.challenges import challenges_routes
from routes.stats import stats_routes
from routes.rewards import reward_routes
from routes.entity_list_routes import entity_list_routes
from routes.handshake import handshake_routes
from routes.bounty_routes import bounty_routes
from routes.other_routes import other_routes
from routes.product_routes import product_routes
from routes.qrcode_routes import qrcode_routes
from routes.material_routes import material_routes
from routes.training_routes import training_routes
from routes.device_routes import device_routes
from routes.brainstem_c2d_routes import brainstem_c2d_routes
from routes.algorithm_proposal_routes import algorithm_proposal_routes
from routes.participant_auth_routes import participant_auth_routes
from flask_swagger import swagger
from security.http_policy import parse_allowed_origins, content_length_bytes
from security.jwt_compat import client_token_error

app = Flask(__name__, static_folder='data')
allowed_origins = parse_allowed_origins(
    config["application"].get("cors_allowed_origins", "")
)
if allowed_origins:
    CORS(
        app,
        origins=allowed_origins,
        allow_headers=["Authorization", "Content-Type"],
        methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        supports_credentials=False,
    )

app.config["JWT_TOKEN_LOCATION"] = ["headers"]

@app.route("/spec")
def spec():
    swag = swagger(app)
    swag["info"]["version"] = config["application"]["version"]
    swag["info"]["title"] = "Crab backend"
    swag["info"]["description"] = "Backend to handle processes"
    return jsonify(swag)

@app.route('/static/<path:filename>')
def serve_static(filename):
    folder_path = '/data'  # Replace with the actual path to your existing folder
    return send_from_directory(folder_path, filename)


@app.route("/.well-known/<path:filename>", methods=["GET"])
def serve_well_known(filename):
    """
    Serve files for ACME challenges / mobile app association, e.g.
    - /.well-known/assetlinks.json
    - /.well-known/apple-app-site-association

    Place files under: public/.well-known/
    """
    folder_path = os.path.join(os.path.dirname(__file__), "public", ".well-known")
    return send_from_directory(folder_path, filename)


app.register_blueprint(authentication_routes)
app.register_blueprint(metadata_routes)
app.register_blueprint(staticdata_routes)
app.register_blueprint(taxonomy_routes, url_prefix="/api/v1/taxonomy")
app.register_blueprint(challenges_routes, url_prefix="/api/v1/challenges")
app.register_blueprint(stats_routes, url_prefix="/api/v1/stats")
app.register_blueprint(reward_routes, url_prefix="/api/v1/rewards")
app.register_blueprint(entity_list_routes, url_prefix="/api/v1/entity-lists")
app.register_blueprint(mission_routes, url_prefix="/api/v1/missions")
app.register_blueprint(bounty_routes, url_prefix="/api/v1/bounty")
app.register_blueprint(handshake_routes, url_prefix="/api/v1/handshake")
app.register_blueprint(other_routes, url_prefix="/api/v1/other")
app.register_blueprint(product_routes, url_prefix="/api/v1/product")
app.register_blueprint(material_routes, url_prefix="/api/v1/material")
app.register_blueprint(qrcode_routes, url_prefix="/api/v1/qrcode")
app.register_blueprint(training_routes, url_prefix="/api/v1/training")
app.register_blueprint(device_routes, url_prefix="/api/v1/devices")
app.register_blueprint(brainstem_c2d_routes)
app.register_blueprint(algorithm_proposal_routes)
app.register_blueprint(participant_auth_routes)
if (
    config.has_section("brainstem_generic_studies")
    and config["brainstem_generic_studies"].getboolean("enabled", fallback=False)
):
    from routes.generic_study_routes import generic_study_routes

    app.register_blueprint(generic_study_routes)

app.secret_key = config["application"]["secret_key"]
app.config["UPLOAD_FOLDER"] = config["application"]["upload_folder"]
app.config["MAX_CONTENT_LENGTH"] = content_length_bytes(
    config["application"].getint("max_content_length_mb", fallback=20)
)
app.config["JWT_SECRET_KEY"] = config["application"]["jwt_secret_string"]
app.config["JWT_BLACKLIST_ENABLED"] = True
app.config["JWT_BLACKLIST_TOKEN_CHECKS"] = ["access", "refresh"]
app.config["JWT_ACCESS_TOKEN_EXPIRES"] = timedelta(
    seconds=config["application"].getint("jwt_access_token_validity")
)
app.config["JWT_REFRESH_TOKEN_EXPIRES"] = timedelta(
    seconds=config["application"].getint("jwt_refresh_token_validity")
)

jwt = JWTManager(app)


@jwt.invalid_token_loader
def invalid_token(reason):
    message, status = client_token_error(reason)
    return jsonify({"msg": message}), status

if not os.path.exists(config["taxonomy"]["image_folder"]):
    os.makedirs(config["taxonomy"]["image_folder"])

if not os.path.exists(config["metadata"]["thumbnail_directory"]):
    os.makedirs(config["metadata"]["thumbnail_directory"])

if not os.path.exists(config["taxonomy"]["labels_folder"]):
    os.makedirs(config["taxonomy"]["labels_folder"])

if not os.path.exists(config["metadata"]["verification_images_directory"]):
    os.makedirs(config["metadata"]["verification_images_directory"])

cache_config = {
    "CACHE_TYPE": "SimpleCache",  # Flask-Caching related configs
    "CACHE_DEFAULT_TIMEOUT": 300
}
app.config.from_mapping(cache_config)
cache = Cache(app)

@jwt.token_in_blocklist_loader
def check_if_token_in_blacklist(jwt_header, jwt_payload):
    jti = jwt_payload['jti']
    return sessions_dao.is_blacklisted(jti)


@app.route("/version")
def version():
    return "Version: {0}".format(config["application"]["version"])


@app.errorhandler(413)
def request_too_large(_error):
    return jsonify({"status": "failed", "message": "Request body is too large"}), 413


@app.route("/", methods=["GET"])
def api():
    """
    Returns index.html file
    """
    return send_file(os.path.join("public", "index.html"))

# @app.errorhandler(Exception)
# def handle_exception(e):
#     # pass through HTTP errors
#     if isinstance(e, HTTPException):
#         return e
#
#     logging.exception(e)
#     # now you're handling non-HTTP exceptions only
#     return render_template("500_generic.html", e=e), 500


if __name__ == "__main__":
    logging.info("Starting backend")
    app.run(debug=config["application"].getboolean("debug"), host="0.0.0.0", port=config["application"]["port"])
