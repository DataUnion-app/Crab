from flask import Blueprint, request, jsonify
import os
from datetime import datetime

from flask_jwt_extended import jwt_required, get_jwt_identity

from commands.training.upload_csv_command import UploadCSVCommand
from commands.training.training_commands import TeamDataOverview, GetStatisticIceHockeyData
from dao.csv_dao import csv_dao

training_routes = Blueprint("training_routes", __name__)

@training_routes.route("/upload-csv", methods=["POST"])
@jwt_required()
def upload_csv():
    public_address = get_jwt_identity()
    if "file" not in request.files:
        return jsonify({
            'status': 'failed',
            'messages': "File does not exist",
        }), 400

    command = UploadCSVCommand(request.files['file'], public_address)
    result = command.execute()

    if command.successful:
        return (
            jsonify({
                "message": "File successfully uploaded",
                "id": result
            }),
            200
        )
    else:
        return (
            jsonify({
                "status": "failed",
                "messages": command.messages
            }),
            400,
        )

@training_routes.route("/get_csv", methods=["GET"])
@jwt_required()
def get_csv():
    page_no = int(request.args.get('page_no'))
    per_page = int(request.args.get('per_page'))

    try:
        csv = csv_dao.get_csv_by_page(page_no, per_page)
        return jsonify({'status': 'success', 'csv': csv})
    except Exception as e:
        return jsonify({
            'status': 'failed',
            'messages': str(e)
        }), 400

@training_routes.route("/last_uploaded_date", methods=["GET"])
@jwt_required()
def last_uploaded_date():
    try:
        csv = csv_dao.get_csv_by_page(1, 1)
        return str(datetime.strptime(csv[0]['created_at'], '%Y-%m-%dT%H:%M:%S.%fUTC').timestamp())
    except Exception as e:
        return jsonify({
            'status': 'failed',
            'messages': str(e)
        }), 400

@training_routes.route("/delete-csv/<string:id>", methods=["DELETE"])
@jwt_required()
def delete_csv(id):
    public_address = get_jwt_identity()
    try:
        csv = csv_dao.get_doc_by_id(id)
        if not csv:
            return jsonify({
                'status': 'failed',
                'messages': "Invalid 'csv_id'"
                }), 400
        uploaded_by = csv.get("uploaded_by")
        if public_address != uploaded_by :
            return jsonify({
                'status': 'failed',
                'messages': "no permission"
                }), 400
        if os.path.exists(csv.get("file_path")):
            os.remove(csv.get("file_path"))
            print("File deleted successfully.")
        else:
            print("File not found.")
        csv_dao.delete_doc(id)
        return jsonify({'status': 'success'}), 200
    except Exception as e:
        return jsonify({
            'status': 'failed',
            'messages': str(e)
        }), 400

@training_routes.route("/get-csv-by-user", methods=["GET"])
@jwt_required()
def get_csv_by_user():
    public_address = get_jwt_identity()
    page_no = int(request.args.get('page_no'))
    per_page = int(request.args.get('per_page'))

    try:
        csv = csv_dao.get_csv_by_user_page(public_address, page_no, per_page)
        return jsonify({'status': 'success', 'csv': csv})
    except Exception as e:
        return jsonify({
            'status': 'failed',
            'messages': str(e)
        }), 400

@training_routes.route("/team-data-overview", methods=["GET"])
@jwt_required()
def team_data_overview():
    page_no = int(request.args.get('page_no'))
    per_page = int(request.args.get('per_page'))

    try:
        command = TeamDataOverview(page_no, per_page)
        result = command.execute()
        return jsonify({'status': 'success', 'result': result})
    except Exception as e:
        return jsonify({
            'status': 'failed',
            'messages': str(e)
        }), 400

@training_routes.route("/get-statistics-icehockey-data", methods=["GET"])
@jwt_required()
def get_statistics_icehockey_data():
    public_address = get_jwt_identity()

    try:
        command = GetStatisticIceHockeyData(public_address)
        result = command.execute()
        return jsonify({'status': 'success', 'result': result})
    except Exception as e:
        return jsonify({
            'status': 'failed',
            'messages': str(e)
        }), 400
