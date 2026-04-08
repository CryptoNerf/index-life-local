"""Voice dictation module using faster-whisper."""
import sys
from flask import Blueprint

bp = Blueprint(
    'voice',
    __name__,
    template_folder='templates',
    static_folder='static',
    static_url_path='/modules/voice/static'
)

REQUIRED_PACKAGES = ['faster_whisper']


def check_dependencies():
    """Check if required packages are installed."""
    if getattr(sys, 'frozen', False):
        from app.modules import check_packages_in_venv
        return check_packages_in_venv(REQUIRED_PACKAGES)

    missing = []
    for name in REQUIRED_PACKAGES:
        try:
            __import__(name)
        except Exception:
            missing.append(name)
    return missing


def init_app(app):
    from . import routes  # noqa: F401
    app.register_blueprint(bp, url_prefix='/voice')
