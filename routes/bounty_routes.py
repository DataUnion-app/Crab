import os
import json

from PIL import Image

from dateutil import parser
from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity, get_jwt
from werkzeug.utils import secure_filename
from dao.qrcode_dao import qrcode_dao
from dao.metadata_dao import image_metadata_dao
from models.metadata.metadata_models import QRCodeStatus, QRCodeType
from commands.bounty.bounty_commands import (
    CreateBountyCommand,
    GetBountyList,
    GetBountyImage,
    GetImagesByBounty,
    HandleImagesOfBounty, GetUserCreatedBountyById, CannotCreateBountyException
)
import logging

from commands.query_view_command import ViewQueryType, QueryViewCommand
from commands.qrcode.qrcode_commands import SetRewardbyQRCodeStatus
from config import config
from models.User import UserRoleType
from models.bounty import BountyType, BountyStatus, Location
from models.db_name import DatabaseName
from dao.bounty_dao import bounty_dao
from decorators.permission import requires_user_role
from models.metadata.metadata_models import Source
from utils.get_qr_code import get_qr_code, get_filepath

bounty_routes = Blueprint("bounty_routes", __name__)


@bounty_routes.route("/", methods=["GET"])
@jwt_required()
def get_bounty_by_id():
    roles = get_jwt()['roles']
    public_address = get_jwt_identity()
    doc_id = request.args.get('id')
    result = bounty_dao.get_doc_by_id(doc_id)
    #c = GetUserCreatedBountyById(public_address, doc_id)
    #result = c.execute()
    #if c.successful:
    return jsonify({"result": result}), 200
    #else:
    #    return jsonify({"messages": c.messages}), 400


@bounty_routes.route("/list", methods=["GET"])
@jwt_required()
def list_bounties():
    roles = [UserRoleType(r) for r in get_jwt()['roles']]
    public_address = get_jwt_identity()
    claims = get_jwt()
    source = Source(claims.get("source"))
    c = GetBountyList(public_address, roles, source)
    result = c.execute()
    if c.successful:
        return jsonify(result), 200
    else:
        return jsonify({'messages': c.messages}), 400


@bounty_routes.route("/create", methods=["POST"])
@jwt_required()
def create_bounty():
    # common
    public_address = get_jwt_identity()
    claims = get_jwt()
    # source = Source(claims.get("source"))
    source = Source.recyclium
    form_data = request.form
    bounty_name = form_data.get("bounty_name", '')
    bounty_description = form_data.get("bounty_description", '')
    dir_path = os.path.join(
        config["application"]["upload_folder"], public_address, "temp"
    )
    if not os.path.exists(dir_path):
        os.makedirs(dir_path)
    bounty_image = request.files['bounty_image']
    if not bounty_image:
        return jsonify({
            'messages': ['The bounty image is empty.']
        }), 400
    bounty_img_handler = Image.open(bounty_image)
    if bounty_img_handler.width < 400 or bounty_img_handler.height < 400:
        return jsonify({
            'messages': ['The bounty image size should be at least 400x400.']
        }), 400
    bounty_image_filename = secure_filename(bounty_image.filename)
    bounty_image_file_path = os.path.join(dir_path, 'bounty-' + bounty_image_filename)
    bounty_img_handler.save(bounty_image_file_path)

    entity_list_ids = form_data.get('entity_list_ids', '[]')
    access_to_user_roles = form_data.get('access_to_user_roles', '[]')
    company_name = form_data.get("company_name", '')
    company_description = form_data.get("company_description", '')
    try:
        bounty_type = BountyType(form_data.get("bounty_type"))
    except Exception as e:
        return jsonify({
            'messages': [f'Not a valid bounty type: [{form_data["bounty_type"]}]']
        }), 400
    try:
        start_date = parser.parse(form_data.get('start_date'))
        end_date = parser.parse(form_data.get('end_date'))
    except Exception as error:
        return jsonify({'messages': [error]}), 400
    tags = form_data.get('tags', '')
    tags = list(map(str.strip, tags.split(',') if tags else []))

    samples = form_data.get('sample_data_list', None)
    samples = list(map(str.strip, samples.split(',') if samples else []))

    image_format = form_data.get('image_format', None)
    image_format = list(map(str.strip, image_format.split(',') if image_format else []))

    rewards_allocated = form_data.get("rewards_allocated")

    entity_list_name = form_data.get('entity_list_name', None)
    image_requirements = form_data.get('image_requirements', None)

    image_count = form_data.get('image_count', None)
    if image_count:
        try:
            image_count = int(image_count)
        except Exception as e:
            image_count = None
            logging.info("Create bounty: image_count [%s] is not a number", image_count)

    number_of_verifications = form_data.get('number_of_verifications', None)
    if number_of_verifications:
        try:
            number_of_verifications = int(number_of_verifications)
        except Exception as e:
            number_of_verifications = None
            logging.info("Create bounty: number_of_verifications [%s] is not a number", number_of_verifications)

    number_of_annotations = form_data.get('number_of_annotations', None)
    if number_of_annotations:
        try:
            number_of_annotations = int(number_of_annotations)
        except Exception as e:
            number_of_annotations = None
            logging.info("Create bounty: number_of_annotations [%s] is not a number", number_of_annotations)
    # not Recyclium
    company_image_file_path = None
    qr_code = None
    if source is not Source.recyclium:
        company_image = request.files['company_image']
        company_img_handler = Image.open(company_image)
        if company_img_handler.width < 400 or company_img_handler.height < 400:
            return jsonify({
                'messages': ['The company image size should be at least 400x400.']
            }), 400
        company_image_filename = secure_filename(company_image.filename)
        company_image_file_path = os.path.join(dir_path, 'company-' + company_image_filename)
        company_img_handler.save(company_image_file_path)
        
        if 'qr_code' in request.files:
            filepath = get_filepath(request.files['qr_code'], 'qrcode_images', public_address)
            qr_code = get_qr_code(filepath)
    
    # Recyclium
    product_id = None
    special_instructions = None
    location = None
    minimum_amount_stored = None
    minimum_amount_returned = None
    amount_of_reward = None
    collection_point = None
    collection_point_description = None

    if source == Source.recyclium:
        print("Source is recyclium")
        product_id = form_data.get('product_id', None)
        special_instructions = form_data.get('special_instructions', None)
        try:
            location = json.loads(form_data.get('location'))
            location = Location._dict(Location(location["latitude"], location["longitude"], location["radius"], location["worldwide"]))
        except Exception as e:
            location = None
        try:
            collection_point = json.loads(form_data.get('collection_point'))
            collection_point = Location._dict(Location(collection_point["latitude"], collection_point["longitude"], collection_point["radius"], collection_point["worldwide"]))
        except Exception as e:
            collection_point = None
        collection_point_description = form_data.get('collection_point_description', None)
        minimum_amount_stored = form_data.get('minimum_amount_stored')
        if minimum_amount_stored:
            try:
                minimum_amount_stored = int(minimum_amount_stored)
            except Exception as e:
                logging.info("Create bounty: minimum_amount_stored [%s] is not a number", minimum_amount_stored)
                return jsonify({
                    'messages': ["Create bounty: minimum_amount_stored [%s] is not a number"]
                }), 400
        minimum_amount_returned = form_data.get('minimum_amount_returned')
        if minimum_amount_returned:
            try:
                minimum_amount_returned = int(minimum_amount_returned)
            except Exception as e:                             
                logging.info("Create bounty: minimum_amount_returned [%s] is not a number", minimum_amount_returned)
                return jsonify({
                    'messages': ["Create bounty: minimum_amount_returned [%s] is not a number"]
                }), 400
        amount_of_items = form_data.get('amount_of_items')
        if amount_of_items:
            try:
                amount_of_items = int(amount_of_items)
                print("amount_of_items: ", amount_of_items)
            except Exception as e:
                logging.info("Create bounty: amount_of_items [%s] is not a number", amount_of_items)
                return jsonify({
                    'messages': ["Create bounty: amount_of_items [%s] is not a number"]
                }), 400
        amount_of_reward = form_data.get('amount_of_reward')
        if amount_of_reward:
            try:
                amount_of_reward = int(amount_of_reward)
            except Exception as e:
                logging.info("Create bounty: amount_of_reward [%s] is not a number", amount_of_reward)
                return jsonify({
                    'messages': ["Create bounty: amount_of_reward [%s] is not a number"]
                }), 400
    batch_ids = json.loads(form_data.get('batch_ids', '[]'))
    number_of_qrcodes = 0
    for batch_id in batch_ids:
        number_of_qrcodes += len(qrcode_dao.get_qrcodes_by_batch_id_and_type(batch_id, QRCodeType.general))
    
    if number_of_qrcodes < amount_of_items:
        return jsonify({
                'messages': ["error: Not enough QR codes for this amount of items."]
            }), 400
    try:
        c = CreateBountyCommand(public_address, company_name, company_description, bounty_type, bounty_name,
                                bounty_description, start_date,
                                end_date, company_image_file_path, bounty_image_file_path, tags, samples,
                                image_requirements, image_format, entity_list_name, product_id, special_instructions, minimum_amount_stored, minimum_amount_returned, amount_of_items, amount_of_reward, location, qr_code, batch_ids, collection_point,collection_point_description, image_count,
                                number_of_verifications,
                                number_of_annotations, entity_list_ids, access_to_user_roles)
        result = c.execute()
        if c.successful:
            logging.info("Created bounty with id [%s]", result['id'])
            return jsonify(result), 200
        else:
            logging.info("Bounty creation failed with messages: %s", c.messages)
            return jsonify({'messages': c.messages}), 400
    except CannotCreateBountyException as e:
        logging.info("Bounty creation failed with messages: %s", str(e))
        return jsonify({'messages': [str(e)]}), 400


@bounty_routes.route("/image", methods=["GET"])
@jwt_required()
def get_bounty_image():
    args = request.args

    bounty_id = args.get('bounty_id')
    image_type = args.get('image_type')

    c = GetBountyImage(bounty_id, image_type)
    result = c.execute()

    if c.successful:
        return result
    else:
        return jsonify({'messages': c.messages}), 400


@bounty_routes.route("/images_ids", methods=["GET"])
@jwt_required()
def get_images_by_bounty():
    args = request.args

    bounty_id = args.get('bounty_id')

    if not bounty_id:
        return jsonify({'messages': 'Bounty id is missing!'}), 400

    bounty_command = GetImagesByBounty(bounty_id)
    result = bounty_command.execute()

    if bounty_command.successful:
        return jsonify(result), 200
    else:
        return jsonify({'messages': bounty_command.messages}), 400


@bounty_routes.route("/image_handler", methods=["POST"])
@jwt_required()
def handle_images_of_bounty():
    public_address = get_jwt_identity()
    data = json.loads(request.data)
    bounty_id = data.get('bounty_id')

    if not bounty_id:
        return jsonify({'messages': 'Bounty id is missing!'}), 400

    image_ids = data.get('image_ids', [])
    accepted_image_ids = []
    rejected_image_ids = []

    for image_id in image_ids:
        qrcode = image_metadata_dao.get_doc_by_id(image_id).get("qr_code")
        if qrcode_dao.is_exist_qrcode_bounty_id_status(qrcode, bounty_id, QRCodeStatus.created):
            accepted_image_ids.append(image_id)
            qrcode_dao.update_status(public_address, qrcode, bounty_id, QRCodeStatus.scanned)
            c = SetRewardbyQRCodeStatus(public_address, bounty_id, image_id, QRCodeStatus.scanned)
            c.execute()
            
        else:
            rejected_image_ids.append(image_id)        

    image_handler_command = HandleImagesOfBounty(public_address,
                                                 bounty_id,
                                                 accepted_image_ids,
                                                 rejected_image_ids)
    result = image_handler_command.execute()

    if image_handler_command.successful:
        return jsonify(result), 200
    else:
        return jsonify({'messages': image_handler_command.messages}), 400


@bounty_routes.route("/query-view", methods=["GET"])
@jwt_required()
def query_view():
    public_address = get_jwt_identity()
    view_name = request.args.get('view')
    design_doc = request.args.get('design-doc')
    query_type = ViewQueryType[request.args.get("query-type")]
    doc_id = request.args.get("doc_id")
    c = QueryViewCommand(public_address, DatabaseName.bounty, design_doc, view_name, query_type, doc_id)
    result = c.execute()
    if c.successful:
        return jsonify({"result": result}), 200
    else:
        return jsonify({"messages": c.messages}), 400

@bounty_routes.route("/<string:id>", methods=["PUT"])
@requires_user_role(UserRoleType.Recyclium_Admin)
@jwt_required()
def update_bounty(id):
    data = json.loads(request.data)
    state = data["state"]
    if not state:
        return jsonify({
                'status': 'failed',
                'messages': "Missing state param in request.",
            }), 400
    has_state = state in iter(BountyStatus)
    if not has_state:
        return jsonify({
                'status': 'failed',
                'messages': "Incorrect state value.",
            }), 400
    result = bounty_dao.update_bounty(id, state)
    
    return jsonify({ "result": result }), 200

@bounty_routes.route("/pending", methods=["GET"])
@jwt_required()
@requires_user_role(UserRoleType.Admin)
def get_pending_bounties():
    page_size = request.args.get('page_size')
    page =  request.args.get('page')
    page_size = int(page_size) if page_size else 10
    page = int(page)-1 if page else 0
    if page_size < 0 or page < 0 :
        resp = jsonify({"message": "Pagination parameters are incorrect."})
        return resp, 400
    pending_bounties = bounty_dao.search_by_status_pagination( BountyStatus["CREATED"], page_size, page ) 
    return jsonify({"status": "success", "pending_bounties": pending_bounties["result"] }), 200

@bounty_routes.route("/progress", methods=["GET"])
@jwt_required()
def get_progress_bounties():
    page_size = request.args.get('page_size')
    page =  request.args.get('page')
    page_size = int(page_size) if page_size else 10
    page = int(page)-1 if page else 0
    if page_size < 0 or page < 0 :
        resp = jsonify({"message": "Pagination parameters are incorrect."})
        return resp, 400
    progress_bounties = bounty_dao.search_by_status_pagination_all_fields( BountyStatus.IN_PROGRESS, page_size, page ) 
    return jsonify({"status": "success", "progress_bounties": progress_bounties["result"] }), 200

@bounty_routes.route("/get-bounties", methods=["GET"])
@jwt_required()
@requires_user_role(UserRoleType.Creator)
def get_bounties():
    public_address = get_jwt_identity()
    bounties = bounty_dao.get_bounties_by_public_address(public_address) 
    return jsonify({"status": "success", "bounties": bounties }), 200
