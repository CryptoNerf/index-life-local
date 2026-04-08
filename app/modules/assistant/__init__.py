"""AI Psychologist module using llama-cpp-python."""
import sys
from flask import Blueprint

bp = Blueprint(
    'assistant',
    __name__,
    template_folder='templates',
    static_folder='static',
    static_url_path='/modules/assistant/static'
)

REQUIRED_PACKAGES = [
    'llama_cpp',
    'sentence_transformers',
    'numpy',
]


def check_dependencies():
    """Check if required packages are installed."""
    if getattr(sys, 'frozen', False):
        from app.modules import check_packages_in_venv
        return check_packages_in_venv(REQUIRED_PACKAGES)

    import logging
    _log = logging.getLogger(__name__)
    missing = []
    for name in REQUIRED_PACKAGES:
        try:
            __import__(name)
        except Exception as exc:
            _log.warning('check_dependencies: %s failed: %s', name, exc)
            missing.append(name)
    return missing


def init_app(app):
    from . import routes  # noqa: F401
    app.register_blueprint(bp, url_prefix='/assistant')
