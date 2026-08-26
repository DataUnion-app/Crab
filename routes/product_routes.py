from flask import current_app
import os,io
import sys, qrcode, json
import zbarlight
import zipfile
from datetime import datetime
from PIL import Image
from flask import Blueprint, jsonify, request, send_file
from flask_jwt_extended import jwt_required, get_jwt_identity, get_jwt
from werkzeug.utils import secure_filename
from PIL import Image
from config import config
from commands.product.product_commands import CreateProductCommand, GetProductById, GetMyProducts, GetAllProducts, GetMyReports, CheckExistQRCode, GenerateQRCode
from commands.metadata.get_metadata_command import GetImagesByQRCodes
from commands.qrcode.qrcode_commands import SetQRCodeStorerToCreator, ReportPDFCreation, ReportCSVCreation, GetQRCodebyBountyID, SetRewardbyQRCodeStatus
from models.metadata.metadata_models import Source, ReportType
from decorators.permission import requires_user_role
from models.User import UserRoleType
from dao.qrcode_dao import qrcode_dao
from dao.bounty_dao import bounty_dao
from dao.report_dao import report_dao
from dao.batch_dao import batch_dao
from dao.metadata_dao import image_metadata_dao
from utils.get_qr_code import get_qr_code, get_filepath
from utils.generate_qr_code import generate_qr_code
from utils.get_hash import get_hash
from models.metadata.metadata_models import QRCodeStatus, QRCodeType

product_routes = Blueprint("product_routes", __name__)
ALLOWED_EXTENSIONS = {'jpg', 'jpeg', 'png', 'gif'}

@product_routes.route("/create", methods=["POST"])
@jwt_required()
@requires_user_role(UserRoleType.Creator)
def create_product():
    public_address = get_jwt_identity()
    claims = get_jwt()
    source = Source(claims.get("source"))

    data = request.form

    dir_path = os.path.join(
        config["application"]["upload_folder"], public_address, "products"
    )
    if not os.path.exists(dir_path):
        os.makedirs(dir_path)

    example_image = request.files['example_image']
    example_image_handler = Image.open(example_image)


    example_image_filename = secure_filename(example_image.filename)
    example_image_file_path = os.path.join(dir_path, example_image_filename)
    example_image_handler.save(example_image_file_path)

    c = CreateProductCommand(public_address, data.get('name'), data.get('material_type'), data.get('material_size'), example_image_file_path, source)
    result = c.execute()
    if c.successful:
        return jsonify({"result": result}), 200
    else:
        return jsonify({"messages": c.messages}), 400


@product_routes.route("/get/<id>", methods=["GET"])
@jwt_required()
@requires_user_role(UserRoleType.Creator)
def get_product_by_id(id):
    c = GetProductById(id)
    result = c.execute()
    if c.successful:
        return jsonify({"result": result}), 200
    else:
        return jsonify({"messages": c.messages}), 400

@product_routes.route("/<id>/example_image", methods=["GET"])
def get_product_examplge_image_by_id(id):
    c = GetProductById(id)
    result = c.execute()

    if c.successful:
        full_path = result.get("example_image")
        if os.path.isfile(full_path):
            return send_file(full_path, as_attachment=True)
        else:
            return jsonify({'status': 'failed','messages': "File not found"}), 400
    else:
        return jsonify({"messages": c.messages}), 400


@product_routes.route("/my-products", methods=["GET"])
@jwt_required()
@requires_user_role(UserRoleType.Creator)
def my_products():
    public_address = get_jwt_identity()
    c = GetMyProducts(public_address)
    result = c.execute()
    if c.successful:
        return jsonify(result), 200
    else:
        return jsonify({'messages': c.messages}), 400

@product_routes.route("/all", methods=["GET"])
@jwt_required()
@requires_user_role(UserRoleType.Recyclium_Admin)
def all():
    c = GetAllProducts()
    result = c.execute()
    if c.successful:
        return jsonify(result), 200
    else:
        return jsonify({'messages': c.messages}), 400

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@product_routes.route("/upload-qrcode", methods=["POST"])
@jwt_required()
def upload_qrcode():
    uploaded_file = request.files.get('file')
    product_id = request.form.get('product_id')
    batch_name = request.form.get('batch_name')
    
    public_address = get_jwt_identity()

    dir_path = os.path.join(
                os.path.abspath(os.curdir),
                config["application"]["upload_folder"],
                'uploaded-qr-code'
            )
    if not os.path.exists(dir_path):
            os.makedirs(dir_path)

    if uploaded_file:
        static_folder = current_app.static_folder
        zip_filename = f"qrcode_zip_{str(datetime.utcnow().timestamp()*1000)}.zip"
        zip_filepath = os.path.join(dir_path, zip_filename)
        uploaded_file.save(zip_filepath)
        zip_relative_filepath = os.path.join(config["application"]["upload_folder"], 'uploaded-qr-code', zip_filename)

    with zipfile.ZipFile(uploaded_file, 'r') as zip_ref:
        batch_size = len(zip_ref.infolist())
        batch_id = batch_dao.create_batch(public_address, product_id, batch_name, batch_size, zip_relative_filepath)
    
    qr_code_images = []
    if uploaded_file.filename.endswith((".zip")):
        with zipfile.ZipFile(uploaded_file, 'r') as zip_ref:
            item_number  = 0
            for qr_code_image in zip_ref.infolist():
                item_number += 1
                if qr_code_image.filename.endswith((".jpg", ".jpeg", ".png")):
                    file_data = zip_ref.read(qr_code_image)
                    image = Image.open(io.BytesIO(file_data))
                    qr_code_filename = f"{public_address}_{product_id}_{batch_id}_{batch_size}_qr_code_{item_number}.png"
                    filepath = os.path.join(dir_path, qr_code_filename)
                    image.save(filepath)
                    qr_code_images.append({
                        "image" : image,
                        "filename" : qr_code_filename
                    })
    else:
        return jsonify({
                    'status': 'failed',
                    'messages': "Filetype must be zip.",
                }), 400
    for qrcode_image in qr_code_images:
        qr_codes = zbarlight.scan_codes(['qrcode'], qrcode_image.get("image"))
        if qr_codes is not None:
            qr_codes = [x.decode('utf-8') for x in qr_codes]
            if qrcode_dao.is_exist(qr_codes):
                return jsonify({
                        'status': 'failed',
                        'messages': "QRCode already exist.",
                    }), 400
            relative_filepath = os.path.join(config["application"]["upload_folder"], 'uploaded-qr-code', qrcode_image.get("filename"))
            hash_value = get_hash(qr_codes[0])
            qrcode_id = qrcode_dao.create_new_qrcode(public_address, product_id, batch_id, qr_codes[0], hash_value, QRCodeStatus.created, False, QRCodeType.general, relative_filepath, Source.recyclium)
    result = {
        "batch_id": batch_id,
        "filepath": zip_relative_filepath
    }

    return jsonify({'status': 'success', 'result' : result}), 200

@product_routes.route("/get-aggregation-qrcode-by-bounty", methods=["POST"])
@jwt_required()
def get_aggregation_qrcode_by_bounty():
    data = json.loads(request.data)
    bounty_id = data.get('bounty_id')
    status = data.get('status')
    if not bounty_id:
            return jsonify({
                'status': 'failed',
                'messages': "Missing parameters in body `bounty_id`",
            }), 400
    qrcodes = qrcode_dao.get_qrcodes_by_bounty_id_status(bounty_id, status)
    c = GetImagesByQRCodes(qrcodes)
    image_ids = c.execute()
    return jsonify({'status': 'success', 'items': image_ids})

@product_routes.route("/get-aggregation-qrcode-by-user", methods=["POST"])
@jwt_required()
def get_aggregation_qrcode_by_user():
    data = json.loads(request.data)
    public_address = data.get('public_address')
    status = data.get('status')
    if not public_address:
            return jsonify({
                'status': 'failed',
                'messages': "Missing parameters in body `public_address`",
            }), 400
    qrcodes = qrcode_dao.get_qrcodes_by_public_address_status(public_address, status)
    c = GetImagesByQRCodes(qrcodes)
    image_ids = c.execute()
    return jsonify({'status': 'success', 'items': image_ids})

@product_routes.route("/get-qrcodes-images", methods=["POST"])
@jwt_required()
def get_qrcode_images():
    data = json.loads(request.data)
    bounty_id = data.get('bounty_id')
    if not bounty_id:
            return jsonify({
                'status': 'failed',
                'messages': "Missing parameters in body `bounty_id`",
            }), 400
    public_address = get_jwt_identity()
    qrcodes = qrcode_dao.get_qrcodes_by_public_address_bounty_id(public_address, bounty_id)
    return jsonify({'status': 'success', 'result': qrcodes})

@product_routes.route("/set-qrcodes-storer-to-creator", methods=["POST"])
@requires_user_role(UserRoleType.Creator)
@jwt_required()
def set_qrcodes_storer_to_creator():
    data = json.loads(request.data)
    bounty_id = data.get('bounty_id')
    public_address = get_jwt_identity()
    c = SetQRCodeStorerToCreator(public_address, bounty_id)
    result = c.execute()
    if c.successful:
        return jsonify({'status': 'success'}), 200
    else:
        return jsonify({'status': 'failed', "messages": c.messages}), 400

@product_routes.route("/check-exist-qrcode-in-bounty", methods=["POST"])
@jwt_required()
def check_exist_qrcode_in_bounty():
    public_address = get_jwt_identity()
    data = json.loads(request.data)
    qrcode = data.get("qrcode")
    bounty_id = data.get("bounty_id")
    c = CheckExistQRCode(public_address, qrcode, bounty_id)
    result = c.execute()
    if c.successful:
        return jsonify({'status': 'success', 'id' : result}), 200
    else:
        return jsonify({'status': 'failed', 'messages': c.messages}), 400

@product_routes.route("/verify-qrcodes", methods=["POST"])
@requires_user_role(UserRoleType.Storer)
@jwt_required()
def verify_qrcodes():
    data = json.loads(request.data)
    qrcodes = data.get('qrcodes')
    status = data.get('status')
    public_address = get_jwt_identity()
    print(public_address)
    if not qrcodes:
            return jsonify({
                'status': 'failed',
                'messages': "Missing parameters in body `qrcodes`",
            }), 400
    for qrcode in qrcodes:
        metadatas = image_metadata_dao.get_image_by_qrcode(qrcode)
        image_id = metadatas[0].get("_id")
        bounty_id = metadatas[0].get("bounty_id")
        qrcode_dao.set_status_by_qrcode(public_address, qrcode, status)
        c = SetRewardbyQRCodeStatus(public_address, bounty_id, image_id, status, qrcode)
        result = c.execute()
        if c.successful:
            return jsonify({'status': 'success', 'result': result }), 200
        else:
            return jsonify({'status': 'failed', "messages": result}), 400

@product_routes.route("/verify-qrcodes-recycler-transport", methods=["POST"])
@requires_user_role(UserRoleType.Recycler)
@jwt_required()
def verify_qrcodes_recycler_transport():
    data = json.loads(request.data)
    qrcodes = data.get('qrcodes')
    public_address = get_jwt_identity()
    if not qrcodes:
        return jsonify({
            'status': 'failed',
            'messages': "Missing parameters in body `qrcodes`",
        }), 400
    print(qrcodes)
    for qrcode in qrcodes:
        qrcode_data = qrcode_dao.get_qrcodes_by_qrcode(qrcode)
        print(qrcode_data[0].get("status"))
        if qrcode_data[0].get("status") != QRCodeStatus.stored:
            return jsonify({'status': 'failed', 'message': qrcode[0] + " status is not stored."}), 400
        qrcode_dao.set_status_by_qrcode_recycler(public_address, qrcode, QRCodeStatus.transport)

    return jsonify({'status': 'success'}), 200

@product_routes.route("/verify-qrcodes-recycler-qualitycheck", methods=["POST"])
@requires_user_role(UserRoleType.Recycler)
@jwt_required()
def verify_qrcodes_recycler_qualitycheck():
    data = json.loads(request.data)
    qrcodes = data.get('qrcodes')
    public_address = get_jwt_identity()
    if not qrcodes:
        return jsonify({
            'status': 'failed',
            'messages': "Missing parameters in body `qrcodes`",
        }), 400
    print(qrcodes)
    for qrcode in qrcodes:
        qrcode_data = qrcode_dao.get_qrcodes_by_qrcode(qrcode)
        print(qrcode_data[0].get("status"))
        if qrcode_data[0].get("status") != QRCodeStatus.transport:
            return jsonify({'status': 'failed', 'message': qrcode[0] + " status is not stored."}), 400
        qrcode_dao.set_status_by_qrcode_recycler(public_address, qrcode, QRCodeStatus.qualitycheck)

    return jsonify({'status': 'success'}), 200

@product_routes.route("/verify-qrcodes-recycler-recycled", methods=["POST"])
@requires_user_role(UserRoleType.Recycler)
@jwt_required()
def verify_qrcodes_recycler_recycled():
    data = json.loads(request.data)
    qrcodes = data.get('qrcodes')
    public_address = get_jwt_identity()
    if not qrcodes:
        return jsonify({
            'status': 'failed',
            'messages': "Missing parameters in body `qrcodes`",
        }), 400
    print(qrcodes)
    for qrcode in qrcodes:
        qrcode_data = qrcode_dao.get_qrcodes_by_qrcode(qrcode)
        print(qrcode_data[0].get("status"))
        if qrcode_data[0].get("status") != QRCodeStatus.qualitycheck:
            return jsonify({'status': 'failed', 'message': qrcode[0] + " status is not stored."}), 400
        qrcode_dao.set_status_by_qrcode_recycler(public_address, qrcode, QRCodeStatus.recycled)

    return jsonify({'status': 'success'}), 200
    
@product_routes.route("/report-creation", methods=["POST"])
@requires_user_role(UserRoleType.Creator)
@jwt_required()
def report_creation():
    data = json.loads(request.data)
    public_address = get_jwt_identity()
    mission_id = data.get('mission_id')
    product_id = data.get('product_id')
    batch_name = data.get('batch_name')
    start_date = data.get('start_date')
    end_date = data.get('end_date')
    filetype = data.get('filetype')

    if filetype != ReportType.pdf and filetype != ReportType.csv:
        return jsonify({'status': 'failed', "messages": "invalide filetype"}), 400
    
    if filetype == ReportType.pdf:
        c = ReportPDFCreation(public_address, mission_id, product_id, batch_name, start_date, end_date)
    else:
        c = ReportCSVCreation(public_address, mission_id, product_id, batch_name, start_date, end_date)

    result = c.execute()

    if c.successful:
        return jsonify({'status': 'success', 'result': result}), 200
    else:
        return jsonify({'status': 'failed', "messages": c.messages}), 400

@product_routes.route("/get-reports", methods=["POST"])
@jwt_required()
@requires_user_role(UserRoleType.Creator)
def get_reports():
    data = json.loads(request.data)
    public_address = get_jwt_identity()
    mission_id = data.get('mission_id')
    start_date = data.get('start_date')
    end_date = data.get('end_date')
    sort_by = data.get('sort_by')
    c = GetMyReports(public_address, mission_id, sort_by, start_date, end_date)
    result = c.execute()
    if c.successful:
        return jsonify({'status': 'success', "result": result}), 200
    else:
        return jsonify({'status': 'failed','messages': c.messages}), 400

@product_routes.route("/download/<string:report_id>", methods=["GET"])
@jwt_required()
@requires_user_role(UserRoleType.Creator)
def download_file(report_id):
    report = report_dao.get_doc_by_id(report_id)
    full_path = report.get("filepath")
    if os.path.isfile(full_path):
        return send_file(full_path, as_attachment=True)
    else:
        return jsonify({'status': 'failed','messages': "File not found"}), 400

@product_routes.route("/generate-qrcode", methods=["POST"])
@jwt_required()
@requires_user_role(UserRoleType.Creator)
def generate_qrcode():
    data = request.form
    public_address = get_jwt_identity()
    product_id = data.get('product_id')
    batch_name = data.get('batch_name')
    batch_size = data.get('batch_size')
    c = GenerateQRCode(public_address, product_id, batch_name, batch_size)
    result = c.execute()
    return jsonify({'status': 'success', 'result': result}), 200

@product_routes.route("/get-all-items-batch-list", methods=["POST"])
@jwt_required()
@requires_user_role(UserRoleType.Creator)
def get_batches():
    data = json.loads(request.data)
    product_id = data.get('product_id')
    page = data.get('page')
    page_size = data.get('page_size')
    skip = (page - 1)*page_size
    qrcodes = qrcode_dao.get_qrcodes_by_product_id(product_id)
    qrcodes = qrcodes.get('result')[skip:skip+(page_size if skip + page_size > len(qrcodes.get('result')) else len(qrcodes.get('result')))]
    return jsonify({'status': 'success', 'result': qrcodes}), 400

@product_routes.route("/get-not-used-batch-list", methods=["POST"])
@jwt_required()
@requires_user_role(UserRoleType.Creator)
def get_not_used_batch_list():
    data = json.loads(request.data)
    product_id = data.get('product_id')
    batch_list = batch_dao.get_all_batches_by_product_id(product_id)
    not_used_batch_list = []
    for batch in batch_list:
        if len(bounty_dao.get_bounties_by_batch_id(batch.get("_id"))) == 0:
            not_used_batch_list.append(batch)
    
    return jsonify({'status': 'success', 'result': not_used_batch_list}), 200

@product_routes.route("/get-all-batch-list", methods=["POST"])
@jwt_required()
@requires_user_role(UserRoleType.Creator)
def get_all_batch_list():
    data = json.loads(request.data)
    product_id = data.get('product_id')
    page = data.get('page')
    page_size = data.get('page_size')
    skip = (page - 1)*page_size
    batch_list = batch_dao.get_all_batches_by_product_id(product_id)
    batch_list = batch_list[skip:skip+(page_size if skip + page_size > len(batch_list) else len(batch_list))]
    return jsonify({'status': 'success', 'result': batch_list}), 200

@product_routes.route("/get-all-batch-for-product", methods=["POST"])
@jwt_required()
@requires_user_role(UserRoleType.Creator)
def get_all_batch_for_product():
    data = json.loads(request.data)
    product_id = data.get('product_id')
    batch_list = batch_dao.get_all_batches_by_product_id(product_id)
    return jsonify({'status': 'success', 'result': batch_list}), 200

@product_routes.route("/get-qrcodes", methods=["GET"])
@jwt_required()
@requires_user_role(UserRoleType.Creator)
def get_qrcodes():
    public_address = get_jwt_identity()
    bounty_id = request.args.get('bounty_id')

    c = GetQRCodebyBountyID(bounty_id)
    result = c.execute()
    if c.successful:
        return jsonify({'status': 'success', "result": result}), 200
    else:
        return jsonify({'status': 'failed','messages': c.messages}), 400

@product_routes.route("/download-batch-qrcodes", methods=["POST"])
@jwt_required()
@requires_user_role(UserRoleType.Creator)
def download_batch_qrcodes():
    public_address = get_jwt_identity()
    batch_id = request.form.get('batch_id')
    batch = batch_dao.get_doc_by_id(batch_id)
    # qrcodes = qrcode_dao.get_qrcodes_by_batch_id(batch_id)
    batch_information = {}
    batch_information["batch"] = batch
    # batch_information["qrcodes"] = qrcodes.get("result")
    
    return jsonify({'status': 'success','batch_information': batch_information}), 200

@product_routes.route("/qrcode-belong-to-bounty", methods=["POST"])
@jwt_required()
def qrcode_belong_to_bounty():
    public_address = get_jwt_identity()
    data = json.loads(request.data)
    qrcode = data.get("qrcode")
    qrcodes = qrcode_dao.get_qrcodes_by_qrcode(qrcode)
    if  len(qrcodes) == 0:
        return jsonify({'status': 'failed','messages': 'QR code is not at all in the backend'}), 400
    if len(qrcodes) >1:
        return jsonify({'status': 'failed','messages': 'Unexpected error. Double qrcode is detected in DB.'}), 400
    batch_id = qrcodes[0].get("batch_id")
    bounties = bounty_dao.get_bounties_by_batch_id(batch_id)
    if len(bounties) == 0:
        return jsonify({'status': 'failed','messages': 'QR code is part of a batch but not connected to a bounty yet'}), 400
    if len(bounties) >1:
        return jsonify({'status': 'failed','messages': 'Unexpected error. The batch that contain this QR code is connected to several bounties.'}), 400
    return jsonify({'status': 'success','bounty_id': bounties[0].get("_id")}), 400
