import os
import sys, qrcode, json
from flask import Blueprint, jsonify, request, send_file
from flask_jwt_extended import jwt_required, get_jwt_identity, get_jwt
from werkzeug.utils import secure_filename
from PIL import Image
from config import config
from models.metadata.metadata_models import Source, ReportType
from decorators.permission import requires_user_role
from models.User import UserRoleType
from dao.material_dao import material_dao


material_routes = Blueprint("material_routes", __name__)

@material_routes.route("/create", methods=["POST"])
@jwt_required()
def create_material():
    public_address = get_jwt_identity()
    data = json.loads(request.data)
    result = material_dao.create_material(public_address, data.get("material_name"))
    if result["success"]:
        return jsonify({'status': 'success', 'message':result["message"],'material_id': result["doc_id"]}), 200
    else:
        return jsonify({'status': 'failed', 'message':result["message"]}), 400

@material_routes.route("/get-all", methods=["GET"])
@jwt_required()
def get_all_materials():
    materials = material_dao.get_all_materials()
    return jsonify({'status': 'success','materials': materials}), 200
