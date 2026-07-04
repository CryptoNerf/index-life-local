"""/backup/restore must only accept paths inside BACKUP_DIR.

The form only ever submits paths produced by list_backups(), so any path
outside the backup folder is a forged or garbled request. Without the
check, POSTing an arbitrary path overwrote diary.db with any readable
SQLite file on disk.
"""
import sqlite3

import pytest

from app.sync_routes import bp as sync_bp


def _make_sqlite(path, marker):
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.execute('CREATE TABLE marker (v TEXT)')
    conn.execute('INSERT INTO marker VALUES (?)', (marker,))
    conn.commit()
    conn.close()


def _read_marker(path):
    conn = sqlite3.connect(str(path))
    try:
        return conn.execute('SELECT v FROM marker').fetchone()[0]
    finally:
        conn.close()


@pytest.fixture
def client(app, tmp_path):
    app.config['SECRET_KEY'] = 'test'
    app.config['DB_PATH'] = tmp_path / 'diary.db'
    app.config['BACKUP_DIR'] = tmp_path / 'backups'
    app.register_blueprint(sync_bp)
    _make_sqlite(tmp_path / 'diary.db', 'current')
    return app.test_client()


def _restore(client, path):
    return client.post('/backup/restore', data={'backup_path': str(path)})


def test_path_outside_backup_dir_is_rejected(client, app, tmp_path):
    evil = tmp_path / 'evil.db'
    _make_sqlite(evil, 'evil')          # valid SQLite — path is the problem

    resp = _restore(client, evil)

    assert resp.status_code == 302
    assert _read_marker(tmp_path / 'diary.db') == 'current'   # untouched


def test_traversal_out_of_backup_dir_is_rejected(client, app, tmp_path):
    evil = tmp_path / 'evil.db'
    _make_sqlite(evil, 'evil')
    sneaky = tmp_path / 'backups' / '..' / 'evil.db'          # resolves outside

    _restore(client, sneaky)

    assert _read_marker(tmp_path / 'diary.db') == 'current'


def test_backup_inside_backup_dir_restores(client, app, tmp_path):
    good = tmp_path / 'backups' / 'diary_20260701_120000.db'
    _make_sqlite(good, 'from-backup')

    _restore(client, good)

    assert _read_marker(tmp_path / 'diary.db') == 'from-backup'


def test_presync_subfolder_backup_is_allowed(client, app, tmp_path):
    good = tmp_path / 'backups' / 'pre-sync' / 'diary_20260701_120000.db'
    _make_sqlite(good, 'from-presync')

    _restore(client, good)

    assert _read_marker(tmp_path / 'diary.db') == 'from-presync'
