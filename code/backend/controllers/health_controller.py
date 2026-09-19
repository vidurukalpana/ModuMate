"""Process liveness endpoint, independent of model initialization."""

from flask import Blueprint

bp = Blueprint("health", __name__)


@bp.get("/health")
def health():
    return "", 200
