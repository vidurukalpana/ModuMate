"""Flask application factory and local development entry point."""

from flask import Flask, jsonify
from flask_cors import CORS
from werkzeug.exceptions import HTTPException

from controllers import api_controller, health_controller, cache_controller
from config import cache_capacity_from_environment
from services.question_answering import QuestionAnsweringService
from services.llm_fallback import LLMFallback
from services.answer_service import AnswerService


def create_app(question_service=None, fallback_service=None, *, cache_capacity=None):
    capacity = cache_capacity_from_environment() if cache_capacity is None else cache_capacity
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = 16 * 1024
    CORS(app)
    app.extensions["question_service"] = (
        question_service if question_service is not None else QuestionAnsweringService()
    )
    app.extensions["fallback_service"] = fallback_service if fallback_service is not None else LLMFallback()
    app.extensions["answer_service"] = AnswerService(
        app.extensions["question_service"], app.extensions["fallback_service"], cache_capacity=capacity)
    app.register_blueprint(health_controller.bp)
    app.register_blueprint(api_controller.bp)
    app.register_blueprint(cache_controller.bp)

    @app.errorhandler(HTTPException)
    def handle_http_error(error):
        response = error.get_response()
        response.data = app.json.dumps({"error": error.description})
        response.content_type = "application/json"
        return response

    @app.errorhandler(Exception)
    def handle_unexpected_error(error):
        app.logger.exception("Unhandled request error")
        return jsonify(error="Internal server error"), 500

    return app


if __name__ == "__main__":
    create_app().run(host="0.0.0.0", port=5000)
