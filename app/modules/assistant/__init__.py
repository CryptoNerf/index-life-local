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
        if importlib.util.find_spec(name) is None:
            missing.append(name)
    return missing


def init_app(app):
    from . import routes  # noqa: F401
    app.register_blueprint(bp, url_prefix='/assistant')
