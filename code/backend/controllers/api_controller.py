"""Question endpoint and request validation."""

from flask import Blueprint, current_app, jsonify, request
from werkzeug.exceptions import BadRequest, UnsupportedMediaType

from services.question_answering import NoAnswerFound, ServiceUnavailable
from services.fallback import simulated_fallback

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
        answer = current_app.extensions["question_service"].answer(question)
    except NoAnswerFound as error:
        return jsonify(simulated_fallback(error.reason)), 200
    except ServiceUnavailable:
        current_app.logger.exception("Question service initialization failed")
        return jsonify(error="Question service is temporarily unavailable"), 503
    return jsonify(answer=answer)
