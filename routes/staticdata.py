from flask import Blueprint
import json

staticdata_routes = Blueprint('staticdata_routes', __name__)


@staticdata_routes.route('/staticdata/tags', methods=["GET"])
def get_all_tags():
    all_tags = {
        "category1": ["abc", "xyz"]
    }
    return json.dumps(all_tags), 200
