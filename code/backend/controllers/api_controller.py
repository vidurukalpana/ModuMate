"""Question endpoint and request validation."""

from flask import Blueprint, current_app, jsonify, request
from werkzeug.exceptions import BadRequest, UnsupportedMediaType

from services.question_answering import ServiceUnavailable
from services.llm_fallback import FallbackError
from services.observability import error_category

bp = Blueprint("api", __name__)
MAX_QUESTION_LENGTH = 2000


@bp.post("/api")
def api():
    if not request.is_json:
        raise UnsupportedMediaType("Content-Type must be application/json")
    data = request.get_json()
    if not isinstance(data, dict):
        raise BadRequest("Request body must be a JSON object")
    question = data.get("question")
    if not isinstance(question, str) or not question.strip():
        raise BadRequest("question must be a non-empty string")
    question = question.strip()
    if len(question) > MAX_QUESTION_LENGTH:
        raise BadRequest(f"question must be at most {MAX_QUESTION_LENGTH} characters")
    if data.get("category") != "MP":
        raise BadRequest("Invalid category; only MP is supported")
    try:
        result = current_app.extensions["answer_service"].answer(question, data['category'])
    except FallbackError as failure:
        error_category(failure.code)
        status = {'timeout': 504, 'provider_unavailable': 503, 'invalid_response': 502}[failure.code]
        return jsonify(error="LLM fallback could not complete the request", code=failure.code), status
    except ServiceUnavailable:
        error_category("model_or_material_unavailable")
        return jsonify(error="Question service is temporarily unavailable"), 503
    return jsonify(result), 200
