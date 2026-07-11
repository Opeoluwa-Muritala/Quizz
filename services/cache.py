"""Tiny per-process cache for frequently read admin JSON endpoints."""
import threading
import time
from functools import wraps

from flask import jsonify, request, session

_cache = {}
_lock = threading.Lock()


def invalidate_admin_cache():
    with _lock:
        _cache.clear()


def cached_admin_json(ttl_seconds=20):
    """Cache successful GET JSON per authenticated admin session and query string."""
    def decorator(func):
        @wraps(func)
        def wrapped(*args, **kwargs):
            if request.method != "GET":
                return func(*args, **kwargs)
            key = (session.get("admin_session_token"), request.full_path)
            now = time.monotonic()
            with _lock:
                item = _cache.get(key)
                if item and item[0] > now:
                    response = jsonify(item[1])
                    response.headers["X-Cache"] = "HIT"
                    response.headers["Cache-Control"] = f"private, max-age={ttl_seconds}"
                    return response
            result = func(*args, **kwargs)
            response = result[0] if isinstance(result, tuple) else result
            status = result[1] if isinstance(result, tuple) and isinstance(result[1], int) else response.status_code
            if status < 400 and response.is_json:
                payload = response.get_json()
                with _lock:
                    _cache[key] = (now + ttl_seconds, payload)
                response.headers["X-Cache"] = "MISS"
                response.headers["Cache-Control"] = f"private, max-age={ttl_seconds}"
            return result
        return wrapped
    return decorator
