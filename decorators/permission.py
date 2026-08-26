from functools import wraps
from commands.whitelist.whitelist_command import WhitelistCommand
from commands.staticdata.get_route_permission_doc import GetRoutePermissionDocCommand

from flask import jsonify
from flask_jwt_extended import get_jwt_identity, get_jwt
from flask_jwt_extended import verify_jwt_in_request

from models.User import UserRoleType


def require_auth_and_whitelisted(fn):
    """
    This is a decorator that requires JWT authentication and
    the wallet address is whitelisted.
    """

    @wraps(fn)
    def wrapper(*args, **kwargs):
        verify_jwt_in_request()
        address = get_jwt_identity()
        whitelist_handler = WhitelistCommand()
        whitelist = whitelist_handler.get_latest_whitelist()

        if address in whitelist:
            return fn(*args, **kwargs)
        else:
            return jsonify(msg="This user is not allowed to access this API!"), 403

    return wrapper


def check_if_enabled(argument):
    """
    This is a decorator that checks if the api is enabled or not
    """

    def decorator_fn(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            from app import app, cache

            with app.app_context():
                permissions = cache.get("permissions")
                if not permissions:
                    permission_command = GetRoutePermissionDocCommand()
                    result = permission_command.execute()

                    if not permission_command.successful:
                        return jsonify(msg=result), 403
                    permissions = result
                    cache.set("permissions", result)
                enabled = permissions.get(argument)

                if enabled:
                    return fn(*args, **kwargs)
                else:
                    return jsonify(msg="The API is not allowed to call!"), 403

        return wrapper

    return decorator_fn


def requires_user_role(user_role: UserRoleType):
    def wrapper(fn):
        @wraps(fn)
        def decorator(*args, **kwargs): 
            verify_jwt_in_request()
            roles = get_jwt()['roles']
            if user_role in roles:
                return fn(*args, **kwargs)
            else:
                return jsonify(msg=f"Requires role [{user_role}]"), 403

        return decorator

    return wrapper