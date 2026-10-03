"""Aggregate cache statistics, plus admin-only cache rows and clearing."""

import hmac

from flask import Blueprint, current_app, jsonify, request

bp = Blueprint('cache', __name__)


@bp.get('/cache/stats')
def stats():
    response = jsonify(current_app.extensions['answer_service'].cache_stats())
    response.headers['Cache-Control'] = 'no-store'
    return response


def _admin_error():
    token = current_app.config['CACHE_ADMIN_TOKEN']
    if not token:
        return jsonify(error='Cache administration is disabled'), 403
    supplied = request.headers.get('Authorization', '')
    if not hmac.compare_digest(supplied.encode(), ('Bearer ' + token).encode()):
        return jsonify(error='Unauthorized'), 401
    return None


@bp.get('/cache/rows')
def rows():
    """Questions and access counts per row; responses are never included."""
    if (error := _admin_error()) is not None:
        return error
    response = jsonify(rows=current_app.extensions['answer_service'].cache_rows())
    response.headers['Cache-Control'] = 'no-store'
    return response


@bp.post('/cache/clear')
def clear():
    if (error := _admin_error()) is not None:
        return error
    response = jsonify(removed=current_app.extensions['answer_service'].clear_cache())
    response.headers['Cache-Control'] = 'no-store'
    return response
