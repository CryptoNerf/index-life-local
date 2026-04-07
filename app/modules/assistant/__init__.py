"""AI Psychologist module using llama-cpp-python."""
import importlib.util
from flask import Blueprint

bp = Blueprint(
    'assistant',
    __name__,
    template_folder='templates',
    static_folder='static',
    static_url_path='/modules/assistant/static'
)

REQUIRED_IMPORTS = [
    'llama_cpp',
    'sentence_transformers',
    'numpy',
]


def check_dependencies():
    missing = []
    for name in REQUIRED_IMPORTS:
        try:
            __import__(name)
        except (ImportError, OSError):
            # ImportError: package not installed
            # OSError: package found but native .so/.dll missing (e.g. llama_cpp)
            missing.append(name)
    return missing


def init_app(app):
    from . import routes  # noqa: F401
    app.register_blueprint(bp, url_prefix='/assistant')
