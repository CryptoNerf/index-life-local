"""
Routes for sync & backup management UI.
"""
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, current_app
from datetime import date

from app import db
from app.models import SyncMeta, SyncConflict
from app.backup import list_backups, backup_and_rotate, restore_backup
from app.sync import (
    get_device_id, get_sync_folder, set_sync_folder,
    get_last_sync, full_sync, scan_and_import, write_changeset_to_folder,
)

bp = Blueprint('sync', __name__)


@bp.route('/sync', methods=['GET'])
def sync_page():
    """Sync & backup settings page."""
    device_id = get_device_id()
    sync_folder = get_sync_folder()
    last_sync = get_last_sync()

    backup_dir = current_app.config.get('BACKUP_DIR', '')
    backups = list_backups(backup_dir) if backup_dir else []

    conflicts = SyncConflict.query.order_by(SyncConflict.resolved_at.desc()).limit(20).all()

    return render_template('sync.html',
                           device_id=device_id,
                           sync_folder=sync_folder,
                           last_sync=last_sync,
                           backups=backups,
                           conflicts=conflicts,
                           current_year=date.today().year)


@bp.route('/sync/settings', methods=['POST'])
def sync_settings():
    """Save sync folder path."""
    folder = request.form.get('sync_folder', '').strip()
    set_sync_folder(folder)
    if folder:
        flash('Sync folder saved', 'success')
    else:
        flash('Sync disabled', 'success')
    return redirect(url_for('sync.sync_page'))


@bp.route('/sync/now', methods=['POST'])
def sync_now():
    """Trigger a full sync cycle."""
    try:
        stats = full_sync(current_app._get_current_object())
        if stats.get('error'):
            flash(stats['error'], 'error')
        else:
            msg_parts = []
            if stats.get('inserted'):
                msg_parts.append(f"{stats['inserted']} new entries")
            if stats.get('updated'):
                msg_parts.append(f"{stats['updated']} updated")
            if stats.get('chat_inserted'):
                msg_parts.append(f"{stats['chat_inserted']} chat messages")
            if stats.get('conflicts'):
                msg_parts.append(f"{stats['conflicts']} conflicts resolved")
            if msg_parts:
                flash('Synced: ' + ', '.join(msg_parts), 'success')
            else:
                flash('Everything is up to date', 'success')
    except Exception as e:
        flash(f'Sync error: {e}', 'error')
    return redirect(url_for('sync.sync_page'))


@bp.route('/sync/export', methods=['POST'])
def sync_export():
    """Manual export of all entries."""
    sync_folder = get_sync_folder()
    if not sync_folder:
        flash('Set a sync folder first', 'error')
        return redirect(url_for('sync.sync_page'))
    try:
        result = write_changeset_to_folder(sync_folder)
        if result:
            flash(f'Exported: {result.name}', 'success')
        else:
            flash('Nothing to export', 'success')
    except Exception as e:
        flash(f'Export error: {e}', 'error')
    return redirect(url_for('sync.sync_page'))


@bp.route('/sync/import', methods=['POST'])
def sync_import():
    """Manual import from sync folder."""
    sync_folder = get_sync_folder()
    if not sync_folder:
        flash('Set a sync folder first', 'error')
        return redirect(url_for('sync.sync_page'))
    try:
        stats = scan_and_import(sync_folder)
        if stats.get('error'):
            flash(stats['error'], 'error')
        elif stats.get('files', 0) > 0:
            flash(f"Imported from {stats['files']} file(s): {stats.get('inserted', 0)} new, {stats.get('updated', 0)} updated", 'success')
        else:
            flash('No new files to import', 'success')
    except Exception as e:
        flash(f'Import error: {e}', 'error')
    return redirect(url_for('sync.sync_page'))


@bp.route('/backup/create', methods=['POST'])
def backup_create():
    """Create a backup now."""
    try:
        db_path = current_app.config['DB_PATH']
        backup_dir = current_app.config['BACKUP_DIR']
        max_count = current_app.config.get('BACKUP_MAX_COUNT', 10)
        result = backup_and_rotate(db_path, backup_dir, max_count)
        if result:
            flash(f'Backup created: {result.name}', 'success')
        else:
            flash('Backup failed', 'error')
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
