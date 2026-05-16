"""Graphics module — mood data visualizations.

Renamed from `insights`. Both the module folder and the Flask
blueprint are now called `graphics`; existing user installs are
migrated transparently — see `_migrate_sentinel()` below.
"""
import os
import sys
from pathlib import Path
from flask import Blueprint

bp = Blueprint(
    'graphics',
    __name__,
    template_folder='templates',
    static_folder='static',
    static_url_path='/modules/graphics/static',
)


def _get_user_data_dir() -> Path:
    from app.modules import _get_user_data_dir as _resolve
    return _resolve()


def sentinel_path() -> Path:
    return _get_user_data_dir() / 'graphics_enabled'


def _legacy_sentinel_path() -> Path:
    """Pre-rename sentinel name. Renamed to `graphics_enabled` at startup."""
    return _get_user_data_dir() / 'insights_enabled'


def _migrate_sentinel():
    """Move `insights_enabled` → `graphics_enabled` for users who were
    on the old name. Runs once on module import; safe to repeat (no-op
    when the new file already exists).
    """
    new = sentinel_path()
    if new.exists():
        return
    old = _legacy_sentinel_path()
    if old.exists():
        try:
            old.rename(new)
        except OSError:
            try:
                new.write_bytes(old.read_bytes())
            except OSError:
                pass


_migrate_sentinel()


def check_dependencies():
    """Graphics has no pip deps — gated by a sentinel file created on install."""
    if sentinel_path().exists():
        return []
    return ['activation']


def init_app(app):
    from . import routes  # noqa: F401
    app.register_blueprint(bp)
