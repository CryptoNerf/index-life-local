"""Deep Mind — neural topic map visualization module."""
from flask import Blueprint

bp = Blueprint(
    'deep_mind',
    __name__,
    template_folder='templates',
    static_folder='static',
    static_url_path='/modules/deep_mind/static',
)

REQUIRED_IMPORTS = ['numpy', 'sklearn']


def check_dependencies():
    """Check if required packages are actually importable."""
    import logging
    _log = logging.getLogger(__name__)
    missing = []
    for name in REQUIRED_IMPORTS:
        try:
            __import__(name)
        except (ImportError, OSError) as exc:
            _log.warning('check_dependencies: %s failed: %s', name, exc)
            missing.append(name)
    return missing


def init_app(app):
    from . import routes  # noqa: F401
    app.register_blueprint(bp, url_prefix='/deep-mind')
