"""
Routes for sync & backup management UI.
"""
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, current_app
from datetime import date

from app.models import SyncConflict
from app.backup import list_backups, backup_and_rotate, restore_backup
from app.sync import (
    get_device_id, get_sync_config, set_sync_config, is_sync_configured,
    get_last_sync, full_sync, import_now, export_now, test_connection,
)

bp = Blueprint('sync', __name__)


@bp.route('/sync', methods=['GET'])
def sync_page():
    """Sync & backup settings page."""
    cfg = get_sync_config()
    backup_dir = current_app.config.get('BACKUP_DIR', '')
    backups = list_backups(backup_dir) if backup_dir else []
    conflicts = SyncConflict.query.order_by(SyncConflict.resolved_at.desc()).limit(20).all()

    return render_template('sync.html',
                           device_id=get_device_id(),
                           sync_mode=cfg['mode'],
                           sync_folder=cfg['folder'],
                           webdav_url=cfg['url'],
                           webdav_user=cfg['username'],
                           webdav_pass=cfg['password'],
                           last_sync=get_last_sync(),
                           backups=backups,
                           conflicts=conflicts,
                           current_year=date.today().year)


@bp.route('/sync/settings', methods=['POST'])
def sync_settings():
    """Save sync configuration (mode + folder/webdav)."""
    mode = request.form.get('sync_mode', 'local').strip()
    folder = request.form.get('sync_folder', '').strip()
    url = request.form.get('webdav_url', '').strip()
    username = request.form.get('webdav_user', '').strip()
    password = request.form.get('webdav_pass', '')

    set_sync_config(mode, folder=folder, url=url, username=username, password=password)
    if is_sync_configured():
        flash('Sync settings saved', 'success')
    else:
        flash('Sync disabled', 'success')
    return redirect(url_for('sync.sync_page'))


@bp.route('/sync/disconnect', methods=['POST'])
def sync_disconnect():
    """Disable sync on this device.

    Wipes the saved folder/URL so `is_sync_configured()` is False and the
    background timer no-ops. Local data is untouched; the snapshot file
    already in the shared folder is left alone so other devices can
    still read what we last pushed.
    """
    set_sync_config('local', folder='', url='', username='', password='')
    flash('Sync disconnected — your data stays on this device', 'success')
    return redirect(url_for('sync.sync_page'))


@bp.route('/sync/test', methods=['POST'])
def sync_test():
    """Test connection to the configured (or posted) backend. JSON response."""
    mode = request.form.get('sync_mode', 'local').strip()
    folder = request.form.get('sync_folder', '').strip()
    url = request.form.get('webdav_url', '').strip()
    username = request.form.get('webdav_user', '').strip()
    password = request.form.get('webdav_pass', '')
    error = test_connection(mode, folder=folder, url=url,
                            username=username, password=password)
    if error:
        return jsonify({'ok': False, 'error': error})
    return jsonify({'ok': True})


@bp.route('/sync/now', methods=['POST'])
def sync_now():
    """Trigger a full sync cycle."""
    try:
        stats = full_sync(current_app._get_current_object())
        if stats.get('error'):
            flash(stats['error'], 'error')
        else:
            _flash_sync_stats(stats)
    except Exception as e:
        flash(f'Sync error: {e}', 'error')
    return redirect(url_for('sync.sync_page'))


@bp.route('/sync/export', methods=['POST'])
def sync_export():
    """Manual push of our snapshot."""
    if not is_sync_configured():
        flash('Configure sync first', 'error')
        return redirect(url_for('sync.sync_page'))
    try:
        ok = export_now(current_app._get_current_object())
        flash('Snapshot uploaded' if ok else 'Upload failed', 'success' if ok else 'error')
    except Exception as e:
        flash(f'Export error: {e}', 'error')
    return redirect(url_for('sync.sync_page'))


@bp.route('/sync/import', methods=['POST'])
def sync_import():
    """Manual pull from peers."""
    if not is_sync_configured():
        flash('Configure sync first', 'error')
        return redirect(url_for('sync.sync_page'))
    try:
        stats = import_now(current_app._get_current_object())
        if stats.get('error'):
            flash(stats['error'], 'error')
        else:
            _flash_sync_stats(stats)
    except Exception as e:
        flash(f'Import error: {e}', 'error')
    return redirect(url_for('sync.sync_page'))


def _flash_sync_stats(stats: dict):
    parts = []
    if stats.get('inserted'):
        parts.append(f"{stats['inserted']} new entries")
    if stats.get('updated'):
        parts.append(f"{stats['updated']} updated")
    if stats.get('chat_inserted'):
        parts.append(f"{stats['chat_inserted']} chat messages")
    if stats.get('conflicts'):
        parts.append(f"{stats['conflicts']} conflicts resolved")
    if parts:
        flash('Synced: ' + ', '.join(parts), 'success')
    else:
        flash('Everything is up to date', 'success')


@bp.route('/backup/create', methods=['POST'])
def backup_create():
    """Create a backup now."""
    try:
        db_path = current_app.config['DB_PATH']
        backup_dir = current_app.config['BACKUP_DIR']
        max_count = current_app.config.get('BACKUP_MAX_COUNT', 10)
        result = backup_and_rotate(db_path, backup_dir, max_count)
        flash(f'Backup created: {result.name}' if result else 'Backup failed',
              'success' if result else 'error')
    except Exception as e:
        flash(f'Backup error: {e}', 'error')
    return redirect(url_for('sync.sync_page'))


@bp.route('/backup/restore', methods=['POST'])
def backup_restore():
    """Restore database from a backup."""
    backup_path = request.form.get('backup_path', '').strip()
    if not backup_path:
        flash('No backup selected', 'error')
        return redirect(url_for('sync.sync_page'))
    try:
        db_path = current_app.config['DB_PATH']
        success = restore_backup(backup_path, db_path)
        if success:
            flash('Database restored. Please restart the application.', 'success')
        else:
            flash('Restore failed — backup may be corrupted', 'error')
    except Exception as e:
        flash(f'Restore error: {e}', 'error')
    return redirect(url_for('sync.sync_page'))
