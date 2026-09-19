"""Flask application factory and local development entry point."""

from flask import Flask, jsonify
from flask_cors import CORS
from werkzeug.exceptions import HTTPException

from controllers import api_controller, health_controller
from services.question_answering import QuestionAnsweringService


def create_app(question_service=None):
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = 16 * 1024
    CORS(app)
    app.extensions["question_service"] = (
        question_service if question_service is not None else QuestionAnsweringService()
    )
    app.register_blueprint(health_controller.bp)
    app.register_blueprint(api_controller.bp)

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
