"""Aggregate cache statistics; no cached content is exposed."""

from flask import Blueprint, current_app, jsonify

bp = Blueprint('cache', __name__)


@bp.get('/cache/stats')
def stats():
    response = jsonify(current_app.extensions['answer_service'].cache_stats())
    response.headers['Cache-Control'] = 'no-store'
    return response
