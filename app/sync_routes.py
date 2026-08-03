"""
Routes for sync & backup management UI.
"""
import threading

from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, current_app
from datetime import date
from pathlib import Path

from app.models import SyncConflict, SyncMeta
from app.backup import list_backups, backup_and_rotate, restore_backup
from app.sync import (
    get_device_id, get_sync_config, set_sync_config, is_sync_configured,
    get_last_sync, get_last_sync_report, full_sync, import_now, export_now,
    test_connection, is_webdav_insecure, list_peer_devices, remove_peer_device,
    _current_backend,
)
from app import sync_vault
from app.i18n import t

bp = Blueprint('sync', __name__)


def _kick_full_sync():
    """Background full sync right after joining/unlocking the vault.

    The whole point of unlocking is to receive the peer's entries — waiting
    for the 2-minute timer makes the flow look broken. Runs in a thread so
    a slow WebDAV folder never blocks the redirect; full_sync serialises on
    its own lock and manages its own app context.
    """
    app_obj = current_app._get_current_object()
    threading.Thread(target=full_sync, args=(app_obj,), daemon=True).start()


@bp.route('/sync', methods=['GET'])
def sync_page():
    """Sync & backup settings page."""
    return _render_sync()


def _gdrive_available() -> bool:
    """Whether the build carries Google Desktop OAuth credentials."""
    from app.google_drive import is_available
    return is_available()


def _gdrive_connected() -> bool:
    """Whether a Google account is linked on this device."""
    from app.google_drive import is_connected
    return is_connected()


def _render_sync(**extra):
    """Render the sync page. `extra` overrides context — used to surface a
    freshly-generated recovery key directly (never through a cookie)."""
    cfg = get_sync_config()
    backup_dir = current_app.config.get('BACKUP_DIR', '')
    backups = list_backups(backup_dir) if backup_dir else []
    conflicts = SyncConflict.query.order_by(SyncConflict.resolved_at.desc()).limit(20).all()
    configured = is_sync_configured()
    backend = _current_backend() if configured else None

    ctx = dict(
        device_id=get_device_id(),
        sync_mode=cfg['mode'],
        sync_folder=cfg['folder'],
        webdav_url=cfg['url'],
        webdav_user=cfg['username'],
        # Only a "is one stored?" flag — the password itself must never be
        # echoed into the HTML (page source, screenshots, devtools dumps).
        webdav_pass_set=bool(cfg['password']),
        last_sync=get_last_sync(),
        sync_report=get_last_sync_report(),
        backups=backups,
        conflicts=conflicts,
        current_year=date.today().year,
        sync_configured=configured,
        encryption=sync_vault.status(backend),
        new_recovery_key=None,
        # "Connect your phone" block: the VK as QR payload + text code.
        # Only present while unlocked — a locked vault has nothing to show.
        pairing_payload=sync_vault.pairing_payload() if configured else None,
        pairing_code=sync_vault.pairing_code() if configured else None,
        gdrive_available=_gdrive_available(),
        gdrive_connected=_gdrive_connected(),
        # device_id -> human name, for the "changes from other devices" list
        peer_names={
            r.key[len('peer_name:'):]: r.value
            for r in SyncMeta.query.filter(SyncMeta.key.like('peer_name:%')).all()
        },
    )
    ctx.update(extra)
    return render_template('sync.html', **ctx)


@bp.route('/sync/settings', methods=['POST'])
def sync_settings():
    """Save sync configuration (mode + folder/webdav)."""
    mode = request.form.get('sync_mode', 'local').strip()
    folder = request.form.get('sync_folder', '').strip()
    url = request.form.get('webdav_url', '').strip()
    username = request.form.get('webdav_user', '').strip()
    password = request.form.get('webdav_pass', '')
    # The form never pre-fills the stored password (see _render_sync), so an
    # empty field means "keep what I have", not "clear it". Clearing happens
    # via Disconnect, which wipes the whole config.
    if not password:
        password = get_sync_config()['password']

    set_sync_config(mode, folder=folder, url=url, username=username, password=password)
    if mode == 'gdrive' and not is_sync_configured():
        # Mode saved but the Google account isn't linked yet — point at the
        # connect button instead of the confusing "sync disabled".
        flash(t('sync.gdrive_connect_first'), 'warning')
    elif is_sync_configured():
        flash(t('sync.flash_settings_saved'), 'success')
        # Saved over plain http — credentials + diary go in clear text.
        if is_webdav_insecure(mode, url):
            flash(t('sync.webdav_insecure'), 'warning')
    else:
        flash(t('sync.flash_disabled'), 'success')
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
    # Also drop the Google link (refresh token) — "disconnect" must not
    # leave a credential behind.
    try:
        from app.google_drive import disconnect as _gdrive_disconnect
        _gdrive_disconnect()
    except Exception as e:
        current_app.logger.warning('google disconnect failed: %s', e)
    flash(t('sync.flash_disconnected'), 'success')
    return redirect(url_for('sync.sync_page'))


# ── Encrypted sync (opt-in) ───────────────────────────────────

@bp.route('/sync/encryption/enable', methods=['POST'])
def encryption_enable():
    """Create a new vault and turn encryption on for this device."""
    if not is_sync_configured():
        flash(t('sync.enc_need_sync'), 'error')
        return redirect(url_for('sync.sync_page'))
    pw = request.form.get('passphrase', '')
    confirm = request.form.get('passphrase_confirm', '')
    if len(pw) < 8:
        flash(t('sync.enc_passphrase_short'), 'error')
        return redirect(url_for('sync.sync_page'))
    if pw != confirm:
        flash(t('sync.enc_passphrase_mismatch'), 'error')
        return redirect(url_for('sync.sync_page'))

    backend = _current_backend()
    try:
        recovery = sync_vault.enable_encryption(backend, pw)
    except FileExistsError:
        # A vault already exists in this folder — join it, don't clobber it.
        flash(t('sync.enc_exists_flash'), 'error')
        return redirect(url_for('sync.sync_page'))
    except Exception as e:
        flash(f'{e}', 'error')
        return redirect(url_for('sync.sync_page'))

    # Replace any plaintext snapshot already in the folder with a sealed one.
    try:
        export_now(current_app._get_current_object())
    except Exception as e:
        current_app.logger.warning('post-enable push failed: %s', e)

    flash(t('sync.enc_enabled_flash'), 'success')
    # Render directly (no redirect) so the one-time recovery key is shown but
    # never travels through a cookie/session.
    return _render_sync(new_recovery_key=recovery)


@bp.route('/sync/encryption/unlock', methods=['POST'])
def encryption_unlock():
    """Unlock the folder's existing vault with passphrase or recovery key."""
    if not is_sync_configured():
        flash(t('sync.enc_need_sync'), 'error')
        return redirect(url_for('sync.sync_page'))
    backend = _current_backend()
    recovery = request.form.get('recovery_key', '').strip()
    pw = request.form.get('passphrase', '')
    try:
        if recovery:
            sync_vault.unlock_with_recovery(backend, recovery)
        else:
            sync_vault.unlock_with_passphrase(backend, pw)
    except ValueError:
        flash(t('sync.enc_no_vault'), 'error')
        return redirect(url_for('sync.sync_page'))
    except Exception:
        # Wrong passphrase / recovery key (CryptoError) — don't echo details.
        flash(t('sync.enc_wrong'), 'error')
        return redirect(url_for('sync.sync_page'))
    flash(t('sync.enc_unlocked_flash'), 'success')
    # Pull the peers' entries right away — that's what unlocking is for.
    _kick_full_sync()
    return redirect(url_for('sync.sync_page'))


@bp.route('/sync/encryption/pair', methods=['POST'])
def encryption_pair():
    """Join the vault with a pairing code shown on another device.

    The no-passphrase path: the phone (or another PC) displays its Vault
    Key as a code, this device pastes it. A wrong code fails loudly
    (verified against the folder's envelopes when any exist).
    """
    if not is_sync_configured():
        flash(t('sync.enc_need_sync'), 'error')
        return redirect(url_for('sync.sync_page'))
    code = request.form.get('pairing_code', '')
    try:
        outcome = sync_vault.adopt_pairing_code(_current_backend(), code)
    except ValueError:
        flash(t('sync.pair_bad_code'), 'error')
        return redirect(url_for('sync.sync_page'))
    flash(t('sync.pair_joined_verified' if outcome == 'verified'
            else 'sync.pair_joined_unverified'), 'success')
    # Full cycle, not just a push: merge the peer's entries immediately AND
    # replace any plaintext snapshot of ours with a sealed one.
    _kick_full_sync()
    return redirect(url_for('sync.sync_page'))


@bp.route('/sync/encryption/lock', methods=['POST'])
def encryption_lock():
    """Forget the cached key on this device (stays enabled; sync pauses)."""
    sync_vault.lock()
    flash(t('sync.enc_locked_flash'), 'success')
    return redirect(url_for('sync.sync_page'))


@bp.route('/sync/google/connect', methods=['POST'])
def google_connect():
    """Link a Google account for the direct Drive-API sync mode.

    Runs the installed-app OAuth flow: opens the browser, waits for the
    loopback redirect (blocking this request thread — fine for a local
    single-user app), stores the refresh token, switches the mode and kicks
    a first sync so the phone's entries appear right away.
    """
    from app import google_drive
    if not google_drive.is_available():
        flash(t('sync.gdrive_setup_hint'), 'error')
        return redirect(url_for('sync.sync_page'))
    try:
        err = google_drive.connect_interactive()
    except Exception as e:
        current_app.logger.warning('google connect crashed: %s', e)
        err = str(e)
    if err:
        flash(t('sync.gdrive_connect_failed', err=err), 'error')
        return redirect(url_for('sync.sync_page'))
    set_sync_config('gdrive')
    flash(t('sync.gdrive_connected'), 'success')
    _kick_full_sync()
    return redirect(url_for('sync.sync_page'))


@bp.route('/sync/devices')
def sync_devices():
    """Devices seen in the sync folder (JSON, plaintext headers only).

    Loaded asynchronously by the /sync page so listing a slow WebDAV
    folder never delays the page render.
    """
    if not is_sync_configured():
        return jsonify({'devices': []})
    try:
        return jsonify({'devices': list_peer_devices(_current_backend())})
    except Exception as e:
        current_app.logger.warning('device listing failed: %s', e)
        return jsonify({'devices': [], 'error': str(e)})


@bp.route('/sync/devices/remove', methods=['POST'])
def sync_devices_remove():
    """Delete a peer device's snapshot from the sync folder.

    A shared folder has no per-device credential to revoke, so this removes
    the device's data and forgets it locally; a device that is still syncing
    will push itself back — the confirm dialog says so.
    """
    device_id = (request.form.get('device_id') or '').strip()
    if not is_sync_configured() or not device_id:
        return jsonify({'ok': False, 'error': 'not configured'}), 400
    if device_id == get_device_id():
        return jsonify({'ok': False, 'error': 'self'}), 400
    try:
        removed = remove_peer_device(_current_backend(), device_id)
    except Exception as e:
        current_app.logger.warning('device removal failed: %s', e)
        return jsonify({'ok': False, 'error': str(e)}), 502
    return jsonify({'ok': bool(removed)})


@bp.route('/sync/discover')
def sync_discover():
    """Scan known cloud-client mounts for candidate sync folders (JSON).

    Powers the "Найти облачные папки" button: folders that already hold
    sync artifacts (the phone's folder) come first, then per-cloud
    suggestions for a fresh setup. Pure local filesystem reads.
    """
    from app.sync_discovery import discover_sync_folders
    try:
        return jsonify({'folders': discover_sync_folders()})
    except Exception as e:
        current_app.logger.warning('sync discovery failed: %s', e)
        return jsonify({'folders': [], 'error': str(e)})


@bp.route('/sync/test', methods=['POST'])
def sync_test():
    """Test connection to the configured (or posted) backend. JSON response."""
    mode = request.form.get('sync_mode', 'local').strip()
    folder = request.form.get('sync_folder', '').strip()
    url = request.form.get('webdav_url', '').strip()
    username = request.form.get('webdav_user', '').strip()
    password = request.form.get('webdav_pass', '')
    # Empty field = "use the stored password" (the form never pre-fills it),
    # so the Test button keeps working without re-typing the password.
    if not password:
        password = get_sync_config()['password']
    error = test_connection(mode, folder=folder, url=url,
                            username=username, password=password)
    warning = t('sync.webdav_insecure') if is_webdav_insecure(mode, url) else None
    if error:
        return jsonify({'ok': False, 'error': error, 'warning': warning})
    return jsonify({'ok': True, 'warning': warning})


# Engine-level error strings → translation keys. The engine returns plain
# strings (it has no request context); the UI maps the known ones so the
# flash follows the interface language.
_ENGINE_ERRORS = {
    'Sync not configured': 'sync.err_not_configured',
    'Sync is already running — try again in a moment': 'sync.err_busy',
}


def _flash_engine_error(msg: str):
    key = _ENGINE_ERRORS.get(msg)
    flash(t(key) if key else msg, 'error')


@bp.route('/sync/now', methods=['POST'])
def sync_now():
    """Trigger a full sync cycle."""
    try:
        stats = full_sync(current_app._get_current_object())
        if stats.get('error'):
            _flash_engine_error(stats['error'])
        else:
            _flash_sync_stats(stats)
    except Exception as e:
        flash(t('sync.flash_sync_error', err=e), 'error')
    return redirect(url_for('sync.sync_page'))


@bp.route('/sync/export', methods=['POST'])
def sync_export():
    """Manual push of our snapshot."""
    if not is_sync_configured():
        flash(t('sync.flash_configure_first'), 'error')
        return redirect(url_for('sync.sync_page'))
    try:
        ok = export_now(current_app._get_current_object())
        if ok:
            flash(t('sync.flash_uploaded'), 'success')
        else:
            flash(t('sync.flash_upload_failed'), 'error')
    except Exception as e:
        flash(t('sync.flash_export_error', err=e), 'error')
    return redirect(url_for('sync.sync_page'))


@bp.route('/sync/import', methods=['POST'])
def sync_import():
    """Manual pull from peers."""
    if not is_sync_configured():
        flash(t('sync.flash_configure_first'), 'error')
        return redirect(url_for('sync.sync_page'))
    try:
        stats = import_now(current_app._get_current_object())
        if stats.get('error'):
            _flash_engine_error(stats['error'])
        else:
            _flash_sync_stats(stats)
    except Exception as e:
        flash(t('sync.flash_import_error', err=e), 'error')
    return redirect(url_for('sync.sync_page'))


def _flash_sync_stats(stats: dict):
    # Failures first — a skipped peer snapshot means that device's changes
    # silently stop arriving, so it must never hide behind a success flash.
    if stats.get('errors'):
        names = ', '.join((stats.get('error_files') or [])[:5])
        flash(t('sync.errors_flash', count=stats['errors'], files=names),
              'warning')
    if stats.get('push_ok') is False:
        flash(t('sync.push_failed_flash'), 'error')

    parts = []
    if stats.get('inserted'):
        parts.append(t('sync.flash_part_new', n=stats['inserted']))
    if stats.get('updated'):
        parts.append(t('sync.flash_part_updated', n=stats['updated']))
    if stats.get('chat_inserted'):
        parts.append(t('sync.flash_part_chat', n=stats['chat_inserted']))
    if stats.get('conflicts'):
        parts.append(t('sync.flash_part_conflicts', n=stats['conflicts']))
    if parts:
        flash(t('sync.flash_synced', parts=', '.join(parts)), 'success')
    elif not stats.get('errors'):
        flash(t('sync.flash_up_to_date'), 'success')


@bp.route('/backup/create', methods=['POST'])
def backup_create():
    """Create a backup now."""
    try:
        db_path = current_app.config['DB_PATH']
        backup_dir = current_app.config['BACKUP_DIR']
        max_count = current_app.config.get('BACKUP_MAX_COUNT', 10)
        result = backup_and_rotate(db_path, backup_dir, max_count)
        if result:
            flash(t('sync.flash_backup_created', name=result.name), 'success')
        else:
            flash(t('sync.flash_backup_failed'), 'error')
    except Exception as e:
        flash(t('sync.flash_backup_error', err=e), 'error')
    return redirect(url_for('sync.sync_page'))


@bp.route('/backup/restore', methods=['POST'])
def backup_restore():
    """Restore database from a backup.

    The path must resolve inside BACKUP_DIR: the form only ever submits
    paths from list_backups(), so anything else is a forged or garbled
    request — refuse it rather than overwrite the diary with an arbitrary
    SQLite file from disk.
    """
    backup_path = request.form.get('backup_path', '').strip()
    if not backup_path:
        flash(t('sync.flash_no_backup_selected'), 'error')
        return redirect(url_for('sync.sync_page'))
    try:
        db_path = current_app.config['DB_PATH']
        backup_dir = Path(current_app.config['BACKUP_DIR']).resolve()
        candidate = Path(backup_path).resolve()
        if not (candidate.is_file() and candidate.is_relative_to(backup_dir)):
            flash(t('sync.restore_invalid_path'), 'error')
            return redirect(url_for('sync.sync_page'))
        success = restore_backup(candidate, db_path)
        if success:
            flash(t('sync.flash_restored'), 'success')
        else:
            flash(t('sync.flash_restore_failed'), 'error')
    except Exception as e:
        flash(t('sync.flash_restore_error', err=e), 'error')
    return redirect(url_for('sync.sync_page'))
