# index.life — Local mood diary
# https://github.com/CryptoNerf/index-life-local
# Copyright (C) 2026 Émile Alexanyan
#
# Licensed under AGPL-3.0 with additional terms per Section 7
# (preservation of author attribution, no misrepresentation of
# origin). See LICENSE and COPYRIGHT at the root of this project.
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
    # Transitive deps of llama-cpp-python — we install the Vulkan wheel with
    # --no-deps (so pip doesn't replace it with a PyPI build), so these must
    # be checked explicitly. Filesystem-only check in check_packages_in_venv
    # treats `foo.py` or `foo/` as present; both match here.
    'diskcache',
    'jinja2',
    'typing_extensions',
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
