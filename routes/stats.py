from flask import Blueprint, request, jsonify
from flask_jwt_extended import get_jwt_identity, jwt_required

from commands.metadata.my_stats_command import MyStatsCommand
from commands.metadata.my_tag_stats_by_time_command import MyTagStatsByTimeCommand
from commands.metadata.my_tag_stats_command import MyTagStatsCommand
from commands.metadata.stats_command import StatsCommand
from commands.metadata.tags_stats_command import TagStatsCommand

stats_routes = Blueprint('stats_routes', __name__)


@stats_routes.route('/', methods=["GET"])
def get_stats():
    args = request.args
    required_params = {'start_time', 'end_time', 'interval'}

    if not all(elem in args.keys() for elem in required_params):
        return jsonify(
            {"status": "failed",
             "message": "Invalid input body. Expected query parameters :{0}".format(required_params)}), 400
    try:
        stats_command = StatsCommand()
        stats_command.input = {
            'start_time': float(args.get('start_time')),
            'end_time': float(args.get('end_time')),
            'interval': float(args.get('interval'))
        }

        result = stats_command.execute()
        if stats_command.successful:
            response = jsonify(result)
            return response, 200
        else:
            return jsonify({'status': 'failed', 'messages': stats_command.messages}), 400
    except ValueError:
        return jsonify({'status': 'failed', 'messages': ['Value error.']}), 400


@stats_routes.route('/tags', methods=["GET"])
def get_tag_stats():
    get_tag_stats_command = TagStatsCommand()
    result = get_tag_stats_command.execute()
    if get_tag_stats_command.successful:
        return jsonify({'status': 'success', 'result': result}), 200
    else:
        return jsonify({'status': 'failed', 'messages': get_tag_stats_command.messages}), 400


@stats_routes.route('/user-tags', methods=["GET"])
@jwt_required
def get_my_tag_stats():
    get_my_tag_stats_command = MyTagStatsCommand()
    get_my_tag_stats_command.input = {
        'public_address': get_jwt_identity()
    }
    result = get_my_tag_stats_command.execute()
    if get_my_tag_stats_command.successful:
        return jsonify({'status': 'success', 'result': result}), 200
    else:
        return jsonify({'status': 'failed', 'messages': get_my_tag_stats_command.messages}), 400


@stats_routes.route('/user-tag-count', methods=["GET"])
@jwt_required
def get_my_tag_stats2():
    args = request.args
    get_my_tag_stats_by_time_command = MyTagStatsByTimeCommand()
    get_my_tag_stats_by_time_command.input = {
        'public_address': get_jwt_identity(),
        'start_time': float(args.get('start_time')),
        'end_time': float(args.get('end_time')),
        'interval': int(args['interval'])
    }
    result = get_my_tag_stats_by_time_command.execute()
    if get_my_tag_stats_by_time_command.successful:
        return jsonify({'status': 'success', 'result': result}), 200
    else:
        return jsonify({'status': 'failed', 'messages': get_my_tag_stats_by_time_command.messages}), 400


@stats_routes.route('/user-stats', methods=["GET"])
@jwt_required
def get_my_stats():
    args = request.args
    required_params = {'start_time', 'end_time'}
    public_address = get_jwt_identity()
    if not all(elem in args.keys() for elem in required_params):
        return jsonify(
            {"status": "failed",
             "message": "Invalid input body. Expected query parameters :{0}".format(required_params)}), 400
    my_stats_command = MyStatsCommand()
    try:
        my_stats_command.input = {
            'public_address': public_address,
            'group_by': int(args.get('group_by', 24)),
            'start_time': float(args['start_time']),
            'end_time': float(args['end_time']),
            'interval': int(args['interval'])
        }
        response = my_stats_command.execute()
    except ValueError:
        return jsonify({"status": "failed", "messages": ["Value error: Please check if input is correct"]}), 400
    except:
        return jsonify({"status": "failed", "messages": ["Please contact support team."]}), 400

    return response, 200
