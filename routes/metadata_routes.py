from flask import Blueprint, request, jsonify, send_file
import json
import os
import io
import ast
from datetime import datetime
from flask_jwt_extended import jwt_required, get_jwt_identity, get_jwt
from web3 import Web3

from commands.metadata.cvat_data_loader.save_cvat_data import SaveCvatDataCommand
from commands.metadata.get_image_count_of_tag import GetImageCountByTag
from commands.metadata.add_annotation_command import AddAnnotationCommand
from commands.metadata.image_result import ImageResult
from commands.dataunions.wedatanation.web3_monetization_wallet import UpdateWeb3MonetizationWalletAddress, \
    GetWeb3WalletMonetizationNonce
from commands.query_view_command import QueryViewCommand, ViewQueryType
from commands.metadata.query_tags_for_images_command import QueryTagsForImagesCommand
from commands.metadata.search_image_by_tags import SearchImagesByTags
from commands.metadata.mark_as_reported_command import MarkImageAsReportedCommand
from commands.metadata.success_rate import SuccessRate
from commands.metadata.global_succes_rate import GlobalSuccessRate
from commands.metadata.update_monetization_status import UpdateMonetizationStatus
from config import config
from dao.metadata_dao import image_metadata_dao
from dao.users_dao import user_dao
from dao.qrcode_dao import qrcode_dao
from models.User import UserRoleType
from models.db_name import DatabaseName
from models.metadata.annotations.annotation_type import AnnotationType
from models.metadata.metadata_models import MonetizationStatus, Network, Source, EntityType, \
    EntitySubType, QRCodeStatus
from utils.get_random_string import get_random_string
import logging
from security.hashing import hash_image
from commands.metadata.query_metadata_command import QueryMetadataCommand, QueryMetadataCommand2
from commands.metadata.add_new_image_command import AddNewImageCommand
from commands.metadata.add_new_metadata_command import AddNewMetadataCommand
from commands.metadata.upload_media_command import UploadMediaCommand
from commands.metadata.upload_record_command import UploadRecordCommand
from commands.metadata.delete_records_command import DeleteRecordsCommand
from commands.metadata.verify_image_command import VerifyImageCommand
from commands.metadata.get_thumbnail_path import GetThumbnailPath
from commands.metadata.query_tags_by_image_status_command import (
    GetTagsByImageStatusCommand,
)
from commands.metadata.get_image_for_verification import GetImageForVerification
from commands.metadata.query.query_annotations_command import QueryAnnotationsCommand
from commands.metadata.download_video_command import DownloadVideoCommand
from commands.metadata.upload_video_command import UploadVideoCommand
from commands.metadata.search_image_by_status import SearchImagesByStatus
from commands.metadata.search_image_by_location import SearchImageByLocation
from commands.metadata.get_survey_responses_command import GetSurveyResponsesCommand
from commands.metadata.get_my_surveys_command import GetMySurveysCommand
from commands.metadata.get_metadata_command import GetMetadataCommand
from commands.metadata.get_metadata_file_command import GetMetadataFileCommand
from commands.metadata.share_data_live_command import ShareDataLiveCommand, GetShareDataLiveCommand
from decorators.permission import check_if_enabled, require_auth_and_whitelisted, requires_user_role
from task_handler.worker import add_exif_and_verify_image
from commands.metadata.download_file_command import DownloadFileCommand
from commands.metadata.get_tokens_list_command import GetTokensListCommand
from commands.metadata.get_active_location_command import GetActiveLocationCommand
from commands.metadata.brainstem_recording_command import BrainstemRecordingStatisticsCommand, BrainstemRecordingFilterCommand

ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "PNG", "JPG", "JPEG", "GIF"}

metadata_routes = Blueprint("metadata_routes", __name__)


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


@metadata_routes.route("/api/v1/annotate", methods=["POST"])
@check_if_enabled("annotations")
@jwt_required()
def upload_metadata():
    required_params = ["image_id"]
    data = json.loads(request.data)
    public_address = get_jwt_identity()

    if not all(elem in data.keys() for elem in required_params):
        return (
            jsonify(
                {
                    "status": "failed",
                    "message": "Invalid input body. Expected keys :{0}".format(
                        required_params
                    ),
                }
            ),
            400,
        )

    add_new_metadata_command = AddNewMetadataCommand(public_address=public_address, mission_id=None)
    add_new_metadata_command.input = {
        "public_address": public_address,
        "image_id": data.get("image_id"),
        "tags": data.get("tags"),
        "description": data.get("description", None),
    }
    result = add_new_metadata_command.execute()
    if not add_new_metadata_command.successful:
        return (
            jsonify(
                {"status": "failed", "messages": add_new_metadata_command.messages}
            ),
            400,
        )
    return jsonify(result), 200


@metadata_routes.route("/api/v1/videos/upload", methods=["POST"])
@jwt_required()
def upload_video():
    public_address = get_jwt_identity()
    bounty = request.form.get('bounty', ["general"])

    if "file" not in request.files:
        raise Exception("File does not exist")

    command = UploadVideoCommand(request.files['file'], public_address, bounty)
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


@metadata_routes.route("/api/v1/videos/<video_id>/download", methods=["GET"])
@jwt_required()
def download_video_by_id(video_id):
    command = DownloadVideoCommand(video_id)
    path = command.execute()

    if command.successful:
        return send_file(path)

    return (
        jsonify({
            "status": "failed",
            "messages": command.messages
        }),
        400,
    )


@metadata_routes.route("/api/v1/upload-file", methods=["POST"])
@jwt_required()
def upload_file():
    
    # Validate if request is correct
    bounty = request.form.getlist('bounty')

    if len(bounty) == 0:
        bounty = ["general"]

    storage = request.form.get('storage')

    mission_id = request.form.get('mission_id', '')
    public_address = get_jwt_identity()
    public_address = public_address if public_address else ''
    source_info = get_jwt().get("source", None)

    if "file" not in request.files:
        resp = jsonify({"message": "No file part in the request"})
        resp.status_code = 400
        return resp

    file = request.files["file"]

    if file.filename == "":
        resp = jsonify({"message": "No file selected for uploading"})
        return resp, 400

    # Optional parameters
    latitude = request.form.get('latitude')
    longitude = request.form.get('longitude')
    
    locality = request.form.get('locality') if request.form.get("locality") else ""
    city = request.form.get('city') if request.form.get("city") else ""

    qr_code = request.form.get('qr_code')
    
    qrcode_id = None
    qrcode = None
    if qr_code:
        qrcode = qrcode_dao.get_qrcode_by_qr_code(qr_code)
        if qrcode is None:
            resp = jsonify({"message": "No qrcode found"})
            resp.status_code = 400
            return resp
        if qrcode["status"] != QRCodeStatus.created: 
            resp = jsonify({"message": "The qrcode already scanned"})
            resp.status_code = 400
            return resp
        qrcode_id = qrcode["_id"]

    annotations = request.form.get('annotations')
    annotations = ast.literal_eval(annotations) if annotations else annotations

    file_type = request.form.get('file-type')
    add_media_command = UploadMediaCommand(file=file,
                                           uploaded_by=public_address,
                                           bounty=bounty,
                                           mission_id=mission_id,
                                           source=source_info,
                                           file_type=file_type,
                                           storage=storage,
                                           qrcode_id = qrcode_id)
    result = add_media_command.execute()

    if add_media_command.successful:
        if qrcode:
            qrcode["scanned_by"] = public_address
            qrcode["status"] = QRCodeStatus.scanned
            qrcode_dao.update_doc(qrcode_id, qrcode)

        if latitude and longitude:
            new_annotations = [{
                "type": "location",
                "latitude": float(latitude),
                "longitude": float(longitude),
                "locality": locality,
                "city": city
            }]

            add_annotation_command = AddAnnotationCommand(
                public_address=public_address,
                entity_id=result,
                annotations=new_annotations,
                mission_id=None
            )
            add_annotation_command.execute()

            if not add_annotation_command.successful:
                return (
                    jsonify({
                        "status": "failed",
                        "messages": add_annotation_command.messages
                    }), 400
                )
            
        if annotations:
            annotation_command = AddAnnotationCommand(
                public_address=public_address,
                entity_id=result,
                annotations=annotations,
                mission_id=None
            )
            annotation_command.execute()

            if not annotation_command.successful:
                return (
                    jsonify({
                        "status": "failed",
                        "messages": annotation_command.messages
                    }), 400
                )

        if add_media_command.media_type == 'image':
            param = {'image_id': result}

            try:
                add_exif_and_verify_image.apply_async(args=[param])
                logging.debug("Celery task for adding exif and verifying image is started...")
            except Exception as e:
                logging.exception(f"Unable to add exif information for [{result}]", exc_info=e)

        return (
            jsonify({
                "message": "File successfully uploaded",
                "id": result
            }), 200
        )
    else:
        logging.debug(
            "Not allowing address [{}] to upload media.".format(public_address)
        )
        return (
                jsonify({
                    "status": "failed",
                    "messages": add_media_command.messages
                }), add_media_command.error_status
            )


@metadata_routes.route("/api/v1/update-annotation", methods=["POST"])
@jwt_required()
def update_annotation():
    mission_id = request.form.get('mission_id', '')
    public_address = get_jwt_identity()
    public_address = public_address if public_address else ''
    
    entity_id = request.form.get('entity_id')

    # Optional parameters
    latitude = request.form.get('latitude')
    longitude = request.form.get('longitude')
    
    locality = request.form.get('locality') if request.form.get("locality") else ""
    city = request.form.get('city') if request.form.get("city") else ""

    annotations = request.form.get('annotations')
    annotations = ast.literal_eval(annotations) if annotations else annotations
    if not entity_id:
        return (
            jsonify({
                "status": "failed",
                "messages": ["entity_id does not exist"]
            }), 400
        )
    image_metadata_dao.init_annotation(entity_id)

    if latitude and longitude:
        new_annotations = [{
            "type": "location",
            "latitude": float(latitude),
            "longitude": float(longitude),
            "locality": locality,
            "city": city
        }]

        add_annotation_command = AddAnnotationCommand(
            public_address=public_address,
            entity_id=entity_id,
            annotations=new_annotations,
            mission_id=None
        )
        add_annotation_command.execute()

        if not add_annotation_command.successful:
            return (
                jsonify({
                    "status": "failed",
                    "messages": add_annotation_command.messages
                }), 400
            )
            
    if annotations:
        annotation_command = AddAnnotationCommand(
            public_address=public_address,
            entity_id=entity_id,
            annotations=annotations,
            mission_id=None
        )
        annotation_command.execute()

        if not annotation_command.successful:
            return (
                jsonify({
                    "status": "failed",
                    "messages": annotation_command.messages
                }), 400
            )
    
    return (
        jsonify({
            "message": "File Annotation successfully updated",
            "id": entity_id
        }), 200
    )

@metadata_routes.route("/api/v1/my-metadata", methods=["GET"])
@jwt_required()
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

    result = image_metadata_dao.get_metadata_by_address(public_address, page)
    return result


@metadata_routes.route("/api/v1/my-images", methods=["GET"])
@jwt_required()
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
    result = image_metadata_dao.get_images_by_eth_address(
        eth_address=public_address, page=page, fields=fields
    )
    return result, 200


@metadata_routes.route("/api/v1/report-images", methods=["POST"])
@jwt_required()
def report_images():
    try:
        data = json.loads(request.data)
        public_address = get_jwt_identity()
        mark_as_reported_command = MarkImageAsReportedCommand()
        mark_as_reported_command.input = {
            "public_address": public_address,
            "photos": data.get("photos"),
        }

        mark_as_reported_command.execute()

        if mark_as_reported_command.successful:
            return jsonify({"status": "success"}), 200
        else:
            return (
                jsonify(
                    {"status": "failed", "messages": mark_as_reported_command.messages}
                ),
                400,
            )

    except ValueError as e:
        logging.exception(e)
        return jsonify({"status": "failed", "message": "Invalid input body."}), 400


@metadata_routes.route("/api/v1/verify-image", methods=["POST"])
@jwt_required()
def verify_image():
    data = json.loads(request.data)
    public_address = get_jwt_identity()
    image_result = ImageResult()
    result = "correct"

    if data.get("verification"):
        verify_image_c = VerifyImageCommand(public_address=public_address, mission_id=data.get('mission_id'))
        verify_image_c.input = {
            "public_address": public_address,
            "data": data.get("verification"),
            "image_id": data.get("image_id"),
        }
        verify_image_c.execute()
        if not verify_image_c.successful:
            return (
                jsonify(
                    {
                        "status": "failed",
                        "messages": ["Error in verification"] + verify_image_c.messages,
                    }
                ),
                400,
            )

    if data.get("annotation"):
        add_annotation = AddNewMetadataCommand(public_address=public_address, mission_id=data.get('mission_id'))
        add_annotation.input = {
            "public_address": public_address,
            "tags": data["annotation"].get("tags"),
            "description": data["annotation"].get("description"),
            "image_id": data.get("image_id"),
        }
        add_annotation.execute()
        if not add_annotation.successful:
            return (
                jsonify(
                    {
                        "status": "failed",
                        "messages": ["Error in annotation"] + add_annotation.messages,
                    }
                ),
                400,
            )
        result = "incorrect"
        try:
            if image_result.image_metadata_dao.image_result(data.get("image_id"), data["annotation"].get("tags")):
                result = "correct"
        except Exception as e:
            result = "incorrect"

    return jsonify({"status": "success", "result": result}), 200


@metadata_routes.route("/api/v1/query-tags", methods=["POST"])
@jwt_required()
def query_tags_for_images():
    try:
        data = json.loads(request.data)
    except ValueError as e:
        logging.exception(e)
        return (
            jsonify({"status": "failed", "messages": ["Unable to parse json body"]}),
            400,
        )
    public_address = get_jwt_identity()

    query_tags = QueryTagsForImagesCommand()
    query_tags.input = {
        "public_address": public_address,
        "image_ids": data["image_ids"],
    }
    result = query_tags.execute()
    return jsonify({"status": "success", "result": result}), 200


@metadata_routes.route("/api/v1/get-image-by-id", methods=["GET"])
def get_image():
    args = request.args
    img_verify_command = GetImageForVerification(args.get("id"))
    result = img_verify_command.execute()
    if not img_verify_command.successful:
        return jsonify({"status": "failed", "messages": img_verify_command.messages}), 400

    return send_file(result)


@metadata_routes.route("/api/v1/query-metadata", methods=["POST"])
@jwt_required()
def query_metadata():
    data = json.loads(request.data)
    public_address = get_jwt_identity()
    source_info = get_jwt().get("source", Source.default)
    query_metadata_command = None

    try:
        if source_info == Source.default or source_info == Source.ncight:
            bounty = data.get("bounty", "general")
            entity_type = data.get("entity-type", "image")
            page = data.get("page") or 1
            annotation_type: AnnotationType = data.get("type") or AnnotationType.TextTag
            query_metadata_command = QueryMetadataCommand(public_address, page, data["status"], data["fields"],
                                                          annotation_type, entity_type, data.get("tags", []), bounty,
                                                          True)
        else:
            skip = data.get("skip", 0)
            limit = data.get("limit", 100)
            annotation_type = data.get("annotation_type")
            entity_type = EntityType(data.get("type"))
            entity_sub_type = EntitySubType(data.get("sub-type"))

            query_metadata_command = QueryMetadataCommand2(public_address=public_address, source=source_info,
                                                           skip=skip, limit=limit, annotation_type=annotation_type,
                                                           entity_type=entity_type, entity_sub_type=entity_sub_type)
    except Exception as e:
        logging.exception(e, exc_info=True)
        return jsonify({'status': "failed", "messages": ["Please check input body."]}), 400

    try:
        result = query_metadata_command.execute()

        if query_metadata_command.successful:
            return jsonify(result), 200
        else:
            return (
                jsonify({"status": "failed", "messages": query_metadata_command.messages}),
                400,
            )
    except Exception as e:
        logging.exception(e, exc_info=True)
        return jsonify({'status': "failed", "messages": ["Unable to execute query."]}), 400


@metadata_routes.route("/api/v1/search-images", methods=["POST"])
@jwt_required()
def search_images_by_tag():
    try:
        data = json.loads(request.data)
        tag = data.get("tag")
        tags = data.get("tags", [tag])
        page = int(data.get("page"))
        page_size = int(data.get("page_size", 100))
        public_address = get_jwt_identity()
        search_images_command = SearchImagesByTags(public_address, tags, page, page_size)

        search_images_command.input = {
            "page": page,
            "status": data.get("status"),
        }
        result = search_images_command.execute()

        if search_images_command.successful:
            return jsonify(result), 200
        else:
            return (
                jsonify(
                    {"status": "failed", "messages": search_images_command.messages}
                ),
                400,
            )

    except ValueError:
        return jsonify({"status": "failed", "messages": "Unable to parse data"}), 400


@metadata_routes.route("/api/v1/metadata/search-images-by-tags", methods=["POST"])
@jwt_required()
def search_images_by_tags():
    try:
        public_address = get_jwt_identity()
        data = json.loads(request.data)
        page_size = data.get("page_size", 100)
        search_images_command = SearchImagesByTags(public_address, data.get("tags"), int(data.get("page")), page_size)
        result = search_images_command.execute()

        if search_images_command.successful:
            return jsonify({"result": result}), 200
        else:
            return (
                jsonify(
                    {"status": "failed", "messages": search_images_command.messages}
                ),
                400,
            )

    except ValueError:
        return jsonify({"status": "failed", "messages": "Unable to parse data"}), 400


@metadata_routes.route('/api/v1/search-images-by-status', methods=["GET"])
@require_auth_and_whitelisted
def search_images_by_status():
    try:
        args = request.args
        page = args.get('page') if args.get('page') else 1
        search_images_command = SearchImagesByStatus(int(page), args.get('status'))
        result = search_images_command.execute()

        if search_images_command.successful:
            return jsonify({'result': result}), 200
        else:
            return jsonify({'status': 'failed', 'messages': search_images_command.messages}), 400

    except ValueError:
        return jsonify({'status': 'failed', 'messages': "Unable to parse data"}), 400

@metadata_routes.route("/api/v1/search-images-by-location", methods=["GET"])
def search_images_by_location():
    try:
        args = request.args
        latitude = args.get('latitude')
        longitude = args.get('longitude')
        range = args.get('range') if args.get('range') else 1
        search_images_command = SearchImageByLocation(float(latitude), float(longitude), float(range))
        result = search_images_command.execute()

        if search_images_command.successful:
            return jsonify({'result': result}), 200
        else:
            return jsonify({'status': 'failed', 'messages': search_images_command.messages}), 400
    except ValueError:
        return jsonify({'status': 'failed', 'messages': "Unable to parse data"}), 400

@metadata_routes.route("/api/v1/metadata/success-rate", methods=["GET"])
@jwt_required()
def user_success_rate():
    try:
        public_address = get_jwt_identity()
        success_rate = SuccessRate()
        success_rate.input = {
            "public_address": public_address
        }
        result = success_rate.execute()

        if success_rate.successful:
            return jsonify({"result": result}), 200
        else:
            return (
                jsonify(
                    {"status": "failed", "messages": success_rate.messages}
                ),
                400,
            )

    except ValueError:
        return jsonify({"status": "failed", "messages": "Unable to parse data"}), 400


@metadata_routes.route("/api/v1/metadata/global-success-rate", methods=["GET"])
@jwt_required()
def global_success_rate():
    try:
        public_address = get_jwt_identity()
        global_success_rate = GlobalSuccessRate()
        result = global_success_rate.execute()

        if global_success_rate.successful:
            return jsonify({"result": result}), 200
        else:
            return (
                jsonify(
                    {"status": "failed", "messages": global_success_rate.messages}
                ),
                400,
            )

    except ValueError:
        return jsonify({"status": "failed", "messages": "Unable to parse data"}), 400


@metadata_routes.route("/api/v1/metadata/global-classification", methods=["GET"])
@jwt_required()
def global_classification():
    try:
        public_address = get_jwt_identity()
        global_success_rate = GlobalSuccessRate()
        result = global_success_rate.execute()

        if global_success_rate.successful:
            return jsonify({"result": result}), 200
        else:
            return (
                jsonify(
                    {"status": "failed", "messages": global_success_rate.messages}
                ),
                400,
            )

    except ValueError:
        return jsonify({"status": "failed", "messages": "Unable to parse data"}), 400


@metadata_routes.route("/api/v1/image/thumbnail", methods=["GET"])
def get_thumbnail():
    # public_address = get_jwt_identity()
    args = request.args
    get_path = GetThumbnailPath()
    get_path.input = {"image_id": args.get("image_id")}
    result = get_path.execute()
    if not get_path.successful:
        return jsonify({"status": "failed", "messages": get_path.messages}), 400

    return send_file(result)


@metadata_routes.route("/api/v1/tags", methods=["GET"])
@jwt_required()
def get_tags_from_db():
    args = request.args
    tags_by_image_status = GetTagsByImageStatusCommand()
    tags_by_image_status.input = {"status": args.get("status")}
    result = tags_by_image_status.execute()
    if tags_by_image_status.successful:
        return jsonify({"status": "success", "tags": result}), 200

    return jsonify({"status": "failed", "messages": tags_by_image_status.messages}), 400


@metadata_routes.route("/api/v1/metadata/annotation", methods=["POST"])
@jwt_required()
def save_annotation():
    source_info = get_jwt().get("source", Source.default)
    public_address = get_jwt_identity()
    add_annotation_command = None

    try:
        data = json.loads(request.data)
    except ValueError as e:
        logging.exception(e)
        return jsonify({"status": "failed", "messages": ["Invalid json body"]}), 400
    if source_info == Source.default:
        add_annotation_command = AddAnnotationCommand(
            public_address, data.get("image_id"), data.get("annotations"), data.get("mission_id")
        )
    else:
        add_annotation_command = AddAnnotationCommand(
            public_address, data.get("entity_id"), data.get("annotations"), data.get("mission_id"),
            save_to_child_doc=True
        )
    add_annotation_command.execute()
    if add_annotation_command.successful:
        return jsonify({"status": "success"}), 200
    else:
        return (
            jsonify({"status": "failed", "messages": add_annotation_command.messages}),
            400,
        )


@metadata_routes.route("/api/v1/metadata/query", methods=["POST"])
@jwt_required()
def query_metadata_annotations():
    try:
        data = json.loads(request.data)
    except ValueError as e:
        logging.exception(e)
        return jsonify({"status": "failed", "messages": ["Invalid json body"]}), 400

    get_annotations_command = QueryAnnotationsCommand(data.get("image_ids"), data.get("annotations"))
    result = get_annotations_command.execute()
    if get_annotations_command.successful:
        return jsonify({"status": "success", 'result': result}), 200
    else:
        return (
            jsonify({"status": "failed", "messages": get_annotations_command.messages}),
            400,
        )


@metadata_routes.route("/api/v1/metadata/tag-image-count", methods=["GET"])
@jwt_required()
def get_image_count_of_tag():
    tag_names = request.args.getlist('tag_name')

    tag_image_count_handler = GetImageCountByTag(tag_names)
    result = tag_image_count_handler.execute()

    if tag_image_count_handler.successful:
        return jsonify({"status": "success", "result": result}), 200

    return jsonify({"status": "failed", "messages": tag_image_count_handler.messages}), 400


@metadata_routes.route("/api/v1/metadata/monetization-status", methods=["POST"])
@jwt_required()
def update_monetization_status():
    data = json.loads(request.data)
    public_address = get_jwt_identity()
    entity_id = data["entity_id"]
    entity_type = data["entity_type"]
    monetization_status = MonetizationStatus[data["monetization_status"]]
    c = UpdateMonetizationStatus(public_address, entity_id, entity_type, monetization_status)
    c.execute()
    if c.successful:
        return jsonify({}), 200
    else:
        return jsonify({"messages": c.messages}), 400


@metadata_routes.route("/api/v1/metadata/query-view", methods=["GET"])
@jwt_required()
def query_view():
    public_address = get_jwt_identity()
    view_name = request.args.get('view')
    design_doc = request.args.get('design-doc')
    query_type = ViewQueryType[request.args.get("query-type")]
    doc_id = request.args.get("doc_id")
    roles = get_jwt()['roles']
    c = QueryViewCommand(public_address, DatabaseName.metadata, design_doc, view_name, query_type, doc_id, roles)
    result = c.execute()
    if c.successful:
        return jsonify({"result": result}), 200
    else:
        return jsonify({"messages": c.messages}), 400


@metadata_routes.route("/api/v1/metadata/web3-wallet", methods=["POST"])
@jwt_required()
def set_web3_monetization_wallet_address():
    public_address = get_jwt_identity()
    data = json.loads(request.data)
    network = Network(data.get("network"))
    c = UpdateWeb3MonetizationWalletAddress(public_address, data.get("wallet_address"), data.get("signature"), network)
    result = c.execute()
    if c.successful:
        return jsonify({"result": result}), 200
    else:
        return jsonify({"messages": c.messages}), 400


@metadata_routes.route("/api/v1/metadata/web3-wallet/nonce", methods=["GET"])
@jwt_required()
def get_web3_monetization_wallet_address_nonce():
    public_address = get_jwt_identity()
    wallet_address = request.args.get('wallet_address')

    c = GetWeb3WalletMonetizationNonce(public_address, wallet_address)
    nonce = c.execute()
    if c.successful:
        return jsonify({"nonce": nonce}), 200
    else:
        return jsonify({"messages": c.messages}), 400


@metadata_routes.route("/api/v1/metadata/cvat-data", methods=["POST"])
@requires_user_role(UserRoleType.User)
def upload_cvat_data():
    public_address = get_jwt_identity()

    data = json.loads(request.data)
    c = SaveCvatDataCommand(public_address, data["bounty_id"], data["annotations"])
    c.execute()
    if c.successful:
        return jsonify({"status": "successful"}), 200

    return jsonify({"messages": c.messages}), 400


@metadata_routes.route("/api/v1/metadata/survey_responses/<survey_id>", methods=["GET"])
@jwt_required()
def survey_responses(survey_id):
    public_address = get_jwt_identity()
    c = GetSurveyResponsesCommand(public_address, survey_id)
    result = c.execute()
    if c.successful:
        return jsonify({"result": result}), 200
    else:
        return jsonify({"messages": c.messages}), 400

@metadata_routes.route("/api/v1/metadata/my_surveys", methods=["GET"])
@jwt_required()
def my_surveys():
    public_address = get_jwt_identity()
    c = GetMySurveysCommand(public_address)
    result = c.execute()
    if c.successful:
        return jsonify({"result": result}), 200
    else:
        return jsonify({"messages": c.messages}), 400

@metadata_routes.route("/api/v1/metadata/<id>", methods=["GET"])
def get_metadata_by_id(id):
    c = GetMetadataCommand(id)
    result = c.execute()
    if c.successful:
        return jsonify({"result": result}), 200
    else:
        return jsonify({"messages": c.messages}), 400

@metadata_routes.route("/api/v1/metadata/file", methods=["GET"])
def get_metadata_file():
    entity_type = request.args.get('entity_type')
    doc_id = request.args.get('doc_id')
    name = request.args.get('name')

    c = GetMetadataFileCommand(entity_type, doc_id, name)
    result = c.execute()
    if c.successful:
        return send_file(result)
    else:
        return jsonify({"messages": c.messages}), 400

@metadata_routes.route("/api/v1/metadata/<metadata_id>/download", methods=["GET"])
@jwt_required()
def download_file_by_id(metadata_id):
    public_address = get_jwt_identity()
    command = DownloadFileCommand(public_address, metadata_id)
    result = command.execute()

    if command.successful:
        return_data = io.BytesIO()
        return_data.write(result["content"])
        # (after writing, cursor will be at last byte, so move it to start)
        return_data.seek(0)
        return send_file(return_data, download_name=result["filename"], as_attachment=True)

    return (
        jsonify({
            "status": "failed",
            "messages": command.messages
        }),
        400,
    )

@metadata_routes.route("/api/v1/metadata/share-data-live", methods=["POST", "GET"])
@jwt_required()
def share_data_live():
    public_address = get_jwt_identity()
    if request.method == "POST":
        data = json.loads(request.data)
        data_sharing_option = data.get('data_sharing_option')
        c = ShareDataLiveCommand(public_address, data_sharing_option)
        result = c.execute()
        if c.successful:
            return jsonify({"result": "success"}), 200
        else:
            return jsonify({"messages": c.messages}), 400
    else:
        public_address = get_jwt_identity()
        c = GetShareDataLiveCommand(public_address)
        result = c.execute()
        if c.successful:
            return jsonify({"data_sharing_option": result}), 200
        else:
            return jsonify({"messages": c.messages}), 400

@metadata_routes.route("/api/v1/metadata/tokens-list", methods=["GET"])
@jwt_required()
def tokens_list():
    wallet_address = request.args.get('wallet_address')
    c = GetTokensListCommand(wallet_address)
    result = c.execute()
    if c.successful:
        return jsonify({"tokens": result}), 200
    else:
        return jsonify({"messages": c.messages}), 400

@metadata_routes.route("/api/v1/metadata/active-location", methods=["GET"])
@jwt_required()
def get_active_location():
    c = GetActiveLocationCommand()
    result = c.execute()
    if c.successful:
        return jsonify({"result": result}), 200
    else:
        return jsonify({"messages": c.messages}), 400


@metadata_routes.route("/api/v1/upload-record", methods=["POST"])
@jwt_required()
def upload_record():
    public_address = get_jwt_identity()
    public_address = public_address if public_address else ''
    source_info = get_jwt().get("source", None)

    logging.debug(f"Upload record by [{public_address}] started")
    if "file" not in request.files:
        logging.debug(f"Upload record by [{public_address}]. No file part in the request")
        resp = jsonify({"message": "No file part in the request"})
        resp.status_code = 400
        return resp

    file = request.files["file"]

    if file.filename == "":
        logging.debug(f"Upload record by [{public_address}]. No file selected for uploading")
        resp = jsonify({"message": "No file selected for uploading"})
        return resp, 400

    try:
        add_record_command = UploadRecordCommand(file=file,
                                                        uploaded_by=public_address)
        result = add_record_command.execute()

        if add_record_command.successful:
            logging.debug(f"Upload record by [{public_address}] success")
            return (
                jsonify({
                    "message": "File successfully uploaded",
                    "id": result
                }), 200
            )
        else:
            logging.debug(f"Unable to upload record by [{public_address}]. [{''.join(add_record_command.messages)}]")
            return (
                jsonify({
                    "status": "failed",
                    "messages": add_record_command.messages
                }), add_record_command.error_status
            )
    except Exception as e:
        logging.exception(f"Unable to upload record by [{public_address}]", exc_info=e)
        return jsonify({"status": "failed", "messages": ["Unable to upload record"]}), 500

@metadata_routes.route("/api/v1/delete-records", methods=["POST"])
@jwt_required()
def delete_records():
    public_address = get_jwt_identity()
    public_address = public_address if public_address else ''
    source_info = get_jwt().get("source", None)

    delete_records_command = DeleteRecordsCommand(uploaded_by=public_address)
    result = delete_records_command.execute()

    if delete_records_command.successful:

        return (
            jsonify({
                "message": "Records deleted"
            }), 200
        )
    else:
        return (
            jsonify({
                "status": "failed",
                "messages": delete_records_command.messages
            }), 400
        )

@metadata_routes.route("/api/v1/get-statistics-brainstem-data", methods=["GET"])
@jwt_required()
def get_statistics_brainstem_data():
    try:
        command = BrainstemRecordingStatisticsCommand()
        result = command.execute()
        return jsonify({'status': 'success', 'result': result})
    except Exception as e:
        return jsonify({
            'status': 'failed',
            'messages': str(e)
        }), 400

@metadata_routes.route("/api/v1/get-filtered-brainstem-data", methods=["GET"])
@jwt_required()
def get_filtered_brainstem_data():
    try:
        args = request.args
        # Create and execute the command with appropriate arguments
        command = BrainstemRecordingFilterCommand(
            recording_type=args.get("recording_type"),
            min_age=int(args.get("min_age", 0)),  # Default min_age to 0
            max_age=int(args.get("max_age", 120)),  # Default max_age to 120
            gender=args.get("gender"),
            ethnicity=args.get("ethnicity"),
            min_amount=int(args.get("min_amount", 0)),  # Default min_amount to 0
            max_amount=int(args.get("max_amount", 1000000)),  # Default max_amount to a high number
            sort_by=args.get("sort_by"),
            sort_direction=args.get("sort_direction"),
            page=int(args.get("page", 0)),
            per_page=int(args.get("per_page", 5))
        )
        result = command.execute()

        return jsonify({'status': 'success', 'result': result})
    except ValueError as ve:
        return jsonify({'status': 'failed', 'message': f"Invalid input: {ve}"}), 400
    except Exception as e:
        return jsonify({'status': 'failed', 'message': str(e)}), 400

@metadata_routes.route("/api/v1/get-brainstem-leaderboard-data", methods=["GET"])
def get_brainstem_leaderboard_data():
    try:
        args = request.args
        # Create and execute the command with appropriate arguments
        command = BrainstemRecordingFilterCommand(
            recording_type=args.get("recording_type"),
            min_age=int(args.get("min_age", 0)),  # Default min_age to 0
            max_age=int(args.get("max_age", 120)),  # Default max_age to 120
            gender=args.get("gender"),
            ethnicity=args.get("ethnicity"),
            min_amount=int(args.get("min_amount", 0)),  # Default min_amount to 0
            max_amount=int(args.get("max_amount", 1000000)),  # Default max_amount to a high number
            sort_by=args.get("sort_by"),
            sort_direction=args.get("sort_direction"),
            page=int(args.get("page", 0)),
            per_page=int(args.get("per_page", 5))
        )
        result = command.execute()

        return jsonify({'status': 'success', 'result': result})
    except ValueError as ve:
        return jsonify({'status': 'failed', 'message': f"Invalid input: {ve}"}), 400
    except Exception as e:
        return jsonify({'status': 'failed', 'message': str(e)}), 400
