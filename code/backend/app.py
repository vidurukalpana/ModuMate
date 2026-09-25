"""Flask application factory and local development entry point."""

from flask import Flask, jsonify
from flask_cors import CORS
from werkzeug.exceptions import HTTPException

from controllers import api_controller, health_controller, cache_controller, observability_controller
import os

from config import cache_capacity_from_environment, cache_ttl_from_environment
from services.question_answering import QuestionAnsweringService
from services.llm_fallback import LLMFallback
from services.answer_service import AnswerService
from services.semantic_cache import SemanticCacheConfig
from services.concurrency import ConcurrencyConfig
from services.observability import install_observability, error_category


def create_app(question_service=None, fallback_service=None, *, cache_capacity=None, semantic_config=None, cache_ttl=None, cache_admin_token=None, metrics_token=None, concurrency_config=None):
    capacity = cache_capacity_from_environment() if cache_capacity is None else cache_capacity
    semantic = semantic_config if semantic_config is not None else SemanticCacheConfig.from_environment()
    ttl = cache_ttl_from_environment() if cache_ttl is None else cache_ttl
    concurrency = concurrency_config if concurrency_config is not None else ConcurrencyConfig.from_environment()
    app = Flask(__name__)
    app.config["CACHE_ADMIN_TOKEN"] = os.getenv("CACHE_ADMIN_TOKEN", "") if cache_admin_token is None else cache_admin_token
    app.config["MAX_CONTENT_LENGTH"] = 16 * 1024
    app.config["METRICS_TOKEN"] = os.getenv("METRICS_TOKEN", "") if metrics_token is None else metrics_token
    CORS(app, expose_headers=["X-Request-ID"])
    install_observability(app)
    app.extensions["question_service"] = (
        question_service if question_service is not None else QuestionAnsweringService()
    )
    app.extensions["fallback_service"] = fallback_service if fallback_service is not None else LLMFallback(concurrency_config=concurrency)
    app.extensions["answer_service"] = AnswerService(
        app.extensions["question_service"], app.extensions["fallback_service"], cache_capacity=capacity, semantic_config=semantic, cache_ttl=ttl, concurrency_config=concurrency)
    app.register_blueprint(health_controller.bp)
    app.register_blueprint(api_controller.bp)
    app.register_blueprint(cache_controller.bp)
    app.register_blueprint(observability_controller.bp)

    @app.errorhandler(HTTPException)
    def handle_http_error(error):
        response = error.get_response()
        response.data = app.json.dumps({"error": error.description})
        response.content_type = "application/json"
        return response

    @app.errorhandler(Exception)
    def handle_unexpected_error(error):
        error_category("unexpected_error")
        return jsonify(error="Internal server error"), 500

    return app


if __name__ == "__main__":
    create_app().run(host="0.0.0.0", port=5000)
