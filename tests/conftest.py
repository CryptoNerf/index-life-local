"""Shared pytest fixtures.

The key fixture here is `app`: a *minimal* Flask application bound to a
throwaway file-backed SQLite database. It deliberately does NOT call
`app.create_app()` — that real factory also runs migrations, takes
backups, starts periodic-sync timers and warms up the assistant module,
none of which belong in a unit test. We only need `db` + the models, so
we wire those up by hand and tear them down per test.

A file-backed DB (under pytest's `tmp_path`) is used rather than
`:memory:` on purpose: an in-memory SQLite lives per-connection, so the
table created on one connection is invisible to the next, which trips up
SQLAlchemy's pooling. A temp file sidesteps that and is still fast.
"""
import pytest
from flask import Flask

from app import db as _db


@pytest.fixture
def app(tmp_path):
    application = Flask('index_life_tests')
    db_file = tmp_path / 'test.db'
    application.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{db_file}'
    application.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

    _db.init_app(application)
    with application.app_context():
        import app.models  # noqa: F401 — registers all tables on db.metadata
        _db.create_all()
        try:
            yield application
        finally:
            _db.session.remove()
