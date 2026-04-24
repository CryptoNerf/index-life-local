"""Deep Mind — neural topic map visualization module."""
import sys
from pathlib import Path
from flask import Blueprint

bp = Blueprint(
    'deep_mind',
    __name__,
    template_folder='templates',
    static_folder='static',
    static_url_path='/modules/deep_mind/static',
)

REQUIRED_PACKAGES = ['numpy', 'sklearn', 'hdbscan']


def _data_dir() -> Path:
    from app.modules import _get_user_data_dir
    return _get_user_data_dir()


def sentinel_path() -> Path:
    """Marker file written when the user explicitly installs this module.

    Without it the module would auto-activate whenever assistant's transitive
    deps (numpy, sklearn via sentence-transformers) happen to be present —
    installing assistant shouldn't silently enable neural map.
    """
    return _data_dir() / 'deep_mind_enabled'


def check_dependencies():
    """Require explicit activation via sentinel, then verify pip packages."""
    if not sentinel_path().exists():
        return ['activation']

    if getattr(sys, 'frozen', False):
        from app.modules import check_packages_in_venv
        return check_packages_in_venv(REQUIRED_PACKAGES)

    import logging
    _log = logging.getLogger(__name__)
    missing = []
    for name in REQUIRED_PACKAGES:
        try:
            __import__(name)
        except (ImportError, OSError) as exc:
            _log.warning('check_dependencies: %s failed: %s', name, exc)
            missing.append(name)
    return missing


def init_app(app):
    from . import routes  # noqa: F401
    app.register_blueprint(bp, url_prefix='/deep-mind')
