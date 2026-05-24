"""Tests for the hand-rolled migration runner (`app._run_migrations`).

There is no Alembic here — migrations are versioned, idempotent
`ALTER TABLE` steps gated on column/table existence and stamped into
`sync_meta`. The risk is an upgrade from an old on-disk schema either
missing a column or running twice. So we build a realistic *pre-sync*
(v0) database by hand, run the real migration runner against it, and
assert the schema lands at the current version — then run it again to
prove idempotency.
"""
import sqlite3

import pytest
from flask import Flask
from sqlalchemy import inspect as sqla_inspect

from app import db, SCHEMA_VERSION, _run_migrations, _get_schema_version


# Minimal schema as it existed before any sync/AI/customization work:
# just the two original tables, without uuid/device_id/deleted/language.
_LEGACY_SCHEMA = """
CREATE TABLE mood_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date DATE NOT NULL UNIQUE,
    rating INTEGER NOT NULL,
    note TEXT,
    created_at DATETIME,
    updated_at DATETIME
);
CREATE TABLE user_profile (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username VARCHAR(100) NOT NULL DEFAULT 'User',
    email VARCHAR(120),
    photo_filename VARCHAR(255),
    created_at DATETIME,
    updated_at DATETIME
);
"""


@pytest.fixture
def legacy_app(tmp_path):
    db_file = tmp_path / 'legacy.db'
    con = sqlite3.connect(db_file)
    con.executescript(_LEGACY_SCHEMA)
    con.commit()
    con.close()

    application = Flask('migration_tests')
    application.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{db_file}'
    application.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    db.init_app(application)
    with application.app_context():
        import app.models  # noqa: F401
        try:
            yield application
        finally:
            db.session.remove()


def _columns(table):
    return {c['name'] for c in sqla_inspect(db.engine).get_columns(table)}


def _tables():
    return set(sqla_inspect(db.engine).get_table_names())


def test_legacy_db_upgrades_to_current_schema(legacy_app):
    _run_migrations(legacy_app)

    # Sync columns added to the original tables.
    mood_cols = _columns('mood_entries')
    assert {'uuid', 'device_id', 'deleted'} <= mood_cols

    profile_cols = _columns('user_profile')
    assert 'birthdate' in profile_cols     # v1
    assert 'language' in profile_cols      # v7

    # Tables created by later migrations exist.
    tables = _tables()
    assert {'sync_meta', 'sync_conflicts', 'person_aliases',
            'user_customization'} <= tables

    # Version is stamped to the current target.
    with db.engine.connect() as conn:
        assert _get_schema_version(conn) == SCHEMA_VERSION


def test_migrations_are_idempotent(legacy_app):
    _run_migrations(legacy_app)
    # Running again must not raise and must not change the version.
    _run_migrations(legacy_app)

    with db.engine.connect() as conn:
        assert _get_schema_version(conn) == SCHEMA_VERSION


def test_already_current_db_is_left_alone(app):
    # `app` fixture builds the *current* schema via create_all(). Running
    # migrations on it should be a clean no-op that just stamps the version.
    _run_migrations(app)
    with db.engine.connect() as conn:
        assert _get_schema_version(conn) == SCHEMA_VERSION
