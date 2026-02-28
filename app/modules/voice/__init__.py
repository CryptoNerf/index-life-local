"""Voice dictation module using faster-whisper."""
import importlib.util
from flask import Blueprint

bp = Blueprint(
    'voice',
    __name__,
    template_folder='templates',
    static_folder='static',
    static_url_path='/modules/voice/static'
)

REQUIRED_IMPORTS = [
    'faster_whisper',
]


def check_dependencies():
    missing = []
    for name in REQUIRED_IMPORTS:
        if importlib.util.find_spec(name) is None:
            missing.append(name)
    return missing


def init_app(app):
    from . import routes  # noqa: F401
    app.register_blueprint(bp, url_prefix='/voice')
