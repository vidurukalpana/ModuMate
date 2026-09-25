"""Aggregate cache statistics; no cached content is exposed."""

import hmac

from flask import Blueprint, current_app, jsonify, request

bp = Blueprint('cache', __name__)


@bp.get('/cache/stats')
def stats():
    response = jsonify(current_app.extensions['answer_service'].cache_stats())
    response.headers['Cache-Control'] = 'no-store'
    return response


@bp.post('/cache/clear')
def clear():
    token = current_app.config['CACHE_ADMIN_TOKEN']
    if not token:
        return jsonify(error='Cache administration is disabled'), 403
    supplied = request.headers.get('Authorization', '')
    if not hmac.compare_digest(supplied.encode(), ('Bearer ' + token).encode()):
        return jsonify(error='Unauthorized'), 401
    response = jsonify(removed=current_app.extensions['answer_service'].clear_cache())
    response.headers['Cache-Control'] = 'no-store'
    return response
