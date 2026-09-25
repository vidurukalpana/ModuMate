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
    snapshot = current_app.extensions['metrics'].snapshot()
    snapshot['concurrency'] = current_app.extensions['answer_service'].concurrency.stats()
    from services.llm_fallback import LLMFallback
    fallback = current_app.extensions['fallback_service']
    if isinstance(fallback, LLMFallback):
        snapshot['ollama_concurrency'] = fallback.concurrency.stats()
    response = jsonify(snapshot)
    response.headers['Cache-Control'] = 'no-store'
    return response
