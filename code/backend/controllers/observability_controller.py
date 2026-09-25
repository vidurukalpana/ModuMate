"""Local readiness snapshot and authenticated aggregate metrics."""

import hmac
from flask import Blueprint, current_app, jsonify, request
from services.question_answering import QuestionAnsweringService

bp = Blueprint('observability', __name__)


@bp.get('/ready')
def ready():
    service = current_app.extensions['question_service']
    initialized = isinstance(service, QuestionAnsweringService) and service.is_ready
    response = jsonify(ready=initialized, local_models_initialized=initialized,
                       ollama='not_checked')
    response.status_code = 200 if initialized else 503
    response.headers['Cache-Control'] = 'no-store'
    return response


@bp.get('/metrics')
def metrics():
    token = current_app.config['METRICS_TOKEN']
    if not token:
        return jsonify(error='Metrics access is disabled'), 403
    supplied = request.headers.get('Authorization', '')
    if not hmac.compare_digest(supplied.encode(), ('Bearer ' + token).encode()):
        return jsonify(error='Unauthorized'), 401
    response = jsonify(current_app.extensions['metrics'].snapshot())
    response.headers['Cache-Control'] = 'no-store'
    return response
