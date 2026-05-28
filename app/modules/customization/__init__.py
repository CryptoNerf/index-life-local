# index.life — Local mood diary
# https://github.com/CryptoNerf/index-life-local
# Copyright (C) 2026 Émile Alexanyan
#
# Licensed under AGPL-3.0 with additional terms per Section 7
# (preservation of author attribution, no misrepresentation of
# origin). See LICENSE and COPYRIGHT at the root of this project.
"""Customization module — user-controlled colors, fonts, backgrounds, calendar mosaic.

Sentinel-activated (no Python deps): when the module folder is present and
the sentinel file `customization_enabled` is in the user data dir, the
module loads. The blueprint registers routes for the settings page and
the API; a Flask context processor injects per-request CSS variables
into the <head> of every template based on the saved preferences.

Existing CSS rules use `var(--name, default-value)` so when the module
is inactive (sentinel missing or disabled) the dashboard renders with
the default classic monochrome look — same as before this module existed.
"""
import sys
from pathlib import Path
from flask import Blueprint

bp = Blueprint(
    'customization',
    __name__,
    template_folder='templates',
    static_folder='static',
    static_url_path='/modules/customization/static',
)


def _data_dir() -> Path:
    from app.modules import _get_user_data_dir
    return _get_user_data_dir()


def sentinel_path() -> Path:
    """Marker file written when the user explicitly installs the module."""
    return _data_dir() / 'customization_enabled'


def uploads_dir() -> Path:
    """User-specific uploads (background images, mosaic images, custom fonts).

    Lives in the user data dir alongside diary.db so backup/sync tools
    naturally pick it up. Created lazily by routes that need to write.
    """
    p = _data_dir() / 'customization_uploads'
    p.mkdir(parents=True, exist_ok=True)
    return p


def check_dependencies():
    """No Python deps — gated by the sentinel file."""
    if sentinel_path().exists():
        return []
    return ['activation']


def init_app(app):
    from . import routes  # noqa: F401
    from .context_processor import register_context_processor
    app.register_blueprint(bp)
    register_context_processor(app)
