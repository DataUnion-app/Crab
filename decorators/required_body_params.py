from flask import request, jsonify
from functools import wraps

def required_body_params(*args):
    """Decorator factory to check request data for POST requests and return
    an error if required parameters are missing."""
    required = list(args)
 
    def decorator(fn):
        """Decorator that checks for the required parameters"""
 
        @wraps(fn)
        def wrapper(*args, **kwargs):
            missing = [r for r in required if r not in request.get_json()]
            if missing:
                response = {
                    "status": "error",
                    "message": "Invalid input body. Expected keys :{0}".format(required),
                    "missing": missing
                }
                return jsonify(response), 400
            return fn(*args, **kwargs)
        return wrapper
    return decorator

