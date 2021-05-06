from flask import Blueprint, request, jsonify
from flask_jwt_extended import get_jwt_identity, jwt_required

from commands.stats.overall_stats_command import OverallStatsCommand
from commands.stats.tags_stats_command import TagStatsCommand
from commands.stats.user_stats_command import UserStatsCommand

stats_routes = Blueprint('stats_routes', __name__)


@stats_routes.route('/overall', methods=["GET"])
def get_overall_stats():
    args = request.args
    required_params = {'start_date', 'end_date'}
    if not all(elem in args.keys() for elem in required_params):
        return jsonify(
            {"status": "failed",
             "message": "Invalid input body. Expected query parameters :{0}".format(required_params)}), 400
    overall_stats_c = OverallStatsCommand()
    try:
        overall_stats_c.input = {
            'start_date': args.get('start_date'),
            'end_date': args.get('end_date'),
        }
        response = overall_stats_c.execute()
        if overall_stats_c.successful:
            return {"status": "success", 'result': response}, 200
        else:
            return jsonify({"status": "failed", "messages": overall_stats_c.messages}), 400
    except ValueError:
        return jsonify({"status": "failed", "messages": ["Value error: Please check if input is correct"]}), 400
    except Exception as e:
        return jsonify({"status": "failed", "messages": ["Please contact support team.", e.message]}), 400


@stats_routes.route('/overall-tags', methods=["GET"])
def get_tag_stats():
    args = request.args

    get_tag_stats_command = TagStatsCommand()
    get_tag_stats_command.input = {
        'start_date': args.get('start_date'),
        'end_date': args.get('end_date'),
    }
    result = get_tag_stats_command.execute()

    if get_tag_stats_command.successful:
        return jsonify({'status': 'success', 'result': result}), 200
    else:
        return jsonify({'status': 'failed', 'messages': get_tag_stats_command.messages}), 400


# @stats_routes.route('/summary/user', methods=["GET"])
# @jwt_required
# def get_my_tag_stats():
#     get_my_tag_stats_command = MyTagStatsCommand()
#     get_my_tag_stats_command.input = {
#         'public_address': get_jwt_identity()
#     }
#     result = get_my_tag_stats_command.execute()
#     if get_my_tag_stats_command.successful:
#         return jsonify({'status': 'success', 'result': result}), 200
#     else:
#         return jsonify({'status': 'failed', 'messages': get_my_tag_stats_command.messages}), 400
#

# @stats_routes.route('/user-tag-count', methods=["GET"])
# @jwt_required
# def get_my_tag_stats2():
#     args = request.args
#     get_my_tag_stats_by_time_command = MyTagStatsByTimeCommand()
#     get_my_tag_stats_by_time_command.input = {
#         'public_address': get_jwt_identity(),
#         'start_time': float(args.get('start_time')),
#         'end_time': float(args.get('end_time')),
#         'interval': 24
#     }
#     result = get_my_tag_stats_by_time_command.execute()
#     if get_my_tag_stats_by_time_command.successful:
#         return jsonify({'status': 'success', 'result': result}), 200
#     else:
#         return jsonify({'status': 'failed', 'messages': get_my_tag_stats_by_time_command.messages}), 400
#

@stats_routes.route('/user', methods=["GET"])
@jwt_required
def get_my_stats():
    args = request.args
    required_params = {'start_date', 'end_date'}
    public_address = get_jwt_identity()
    if not all(elem in args.keys() for elem in required_params):
        return jsonify(
            {"status": "failed",
             "message": "Invalid input body. Expected query parameters :{0}".format(required_params)}), 400
    my_stats_command = UserStatsCommand()
    try:
        my_stats_command.input = {
            'public_address': public_address,
            'start_date': args.get('start_date'),
            'end_date': args.get('end_date'),
        }
        response = my_stats_command.execute()
        if my_stats_command.successful:
            return {"status": "success", 'result': response}, 200
        else:
            return jsonify({"status": "failed", "messages": my_stats_command.messages}), 400
    except ValueError:
        return jsonify({"status": "failed", "messages": ["Value error: Please check if input is correct"]}), 400
    except Exception as e:
        return jsonify({"status": "failed", "messages": ["Please contact support team.", e.message]}), 400
