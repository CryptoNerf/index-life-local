"""Insights module — mood data visualizations."""
import os
import sys
from pathlib import Path
from flask import Blueprint

bp = Blueprint(
    'insights',
    __name__,
    template_folder='templates',
    static_folder='static',
    static_url_path='/modules/insights/static',
)


def _get_user_data_dir() -> Path:
    if sys.platform == 'darwin':
        return Path.home() / 'Library' / 'Application Support' / 'index.life'
    elif sys.platform == 'win32':
        return Path(os.environ.get('APPDATA', str(Path.home()))) / 'index.life'
    return Path.home() / '.index-life'


def sentinel_path() -> Path:
    return _get_user_data_dir() / 'insights_enabled'


def check_dependencies():
    """Insights has no pip deps — gated by a sentinel file created on install."""
    if sentinel_path().exists():
        return []
    return ['activation']


def init_app(app):
    from . import routes  # noqa: F401
    app.register_blueprint(bp)
