"""Backups must not carry device-local secrets.

sync_meta caches the sync Vault Key and the WebDAV password. A backup is
exactly the file users copy off the device — often into the same cloud that
holds the encrypted snapshots — so a VK inside it would void the
zero-knowledge design. create_backup scrubs those keys from the copy (never
from the live DB).
"""
import sqlite3

from app.backup import create_backup


def _make_db(path, with_sync_meta=True):
    conn = sqlite3.connect(str(path))
    conn.execute('CREATE TABLE mood (v TEXT)')
    conn.execute("INSERT INTO mood VALUES ('diary data')")
    if with_sync_meta:
        conn.execute('CREATE TABLE sync_meta (key TEXT PRIMARY KEY, value TEXT)')
        conn.executemany('INSERT INTO sync_meta VALUES (?, ?)', [
            ('device_id', 'dev-1'),
            ('webdav_url', 'https://dav.example.com/diary/'),
            ('sync_vault_key', 'U0VDUkVULVZLLWJhc2U2NA=='),
            ('webdav_pass', 'hunter2'),
        ])
    conn.commit()
    conn.close()


def _meta(path):
    conn = sqlite3.connect(str(path))
    try:
        return dict(conn.execute('SELECT key, value FROM sync_meta').fetchall())
    finally:
        conn.close()


def test_backup_drops_vk_and_webdav_password(tmp_path):
    db = tmp_path / 'diary.db'
    _make_db(db)

    backup = create_backup(db, tmp_path / 'backups')

    assert backup is not None
    meta = _meta(backup)
    assert 'sync_vault_key' not in meta
    assert 'webdav_pass' not in meta
    # non-secret config and the data itself survive
    assert meta['device_id'] == 'dev-1'
    assert meta['webdav_url'] == 'https://dav.example.com/diary/'
    conn = sqlite3.connect(str(backup))
    assert conn.execute('SELECT v FROM mood').fetchone()[0] == 'diary data'
    conn.close()


def test_live_database_keeps_its_secrets(tmp_path):
    db = tmp_path / 'diary.db'
    _make_db(db)

    create_backup(db, tmp_path / 'backups')

    meta = _meta(db)
    assert meta['sync_vault_key'] == 'U0VDUkVULVZLLWJhc2U2NA=='
    assert meta['webdav_pass'] == 'hunter2'


def test_backup_works_without_sync_meta_table(tmp_path):
    db = tmp_path / 'diary.db'
    _make_db(db, with_sync_meta=False)   # pre-sync-era database

    backup = create_backup(db, tmp_path / 'backups')

    assert backup is not None and backup.is_file()
