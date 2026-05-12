"""Customization module routes — settings page and JSON API.

Save / reset endpoints are kept tiny and synchronous (no background
work, no LLM, no heavy I/O) so they can hold the SQLite write lock
for only a few milliseconds. The single-row UserCustomization table
is upserted in-place.
"""
import json
import os
import re
import secrets
from datetime import datetime
from pathlib import Path

from flask import (
    jsonify, render_template, request, send_from_directory, abort,
)

from app import db
from app.models import UserCustomization

from . import bp, uploads_dir
from .defaults import DEFAULTS, merge_with_defaults


# ── Validation ────────────────────────────────────────────────

# Accept #rgb, #rrggbb, rgb()/rgba(), or 'transparent'/'none'.  Anything
# unusual is rejected — the JS UI only ever submits well-formed values,
# so this is mainly a defence against direct API misuse.
_HEX_RE = re.compile(r'^#([0-9a-f]{3}|[0-9a-f]{6})$', re.I)
_RGB_RE = re.compile(
    r'^rgba?\(\s*\d{1,3}\s*,\s*\d{1,3}\s*,\s*\d{1,3}\s*'
    r'(?:,\s*(?:0|1|0?\.\d+)\s*)?\)$', re.I,
)


def _is_valid_color(value: str) -> bool:
    if not isinstance(value, str):
        return False
    v = value.strip().lower()
    if v in ('transparent', 'none'):
        return True
    if _HEX_RE.match(v):
        return True
    if _RGB_RE.match(v):
        return True
    return False


# Keys treated as colors (validated as CSS color); everything else is
# subject to per-key validation below.
_COLOR_KEYS = {
    'bg-color', 'text-color', 'heading-color', 'brand-color',
    'cube-filled-color', 'cube-empty-color', 'cube-border-color',
    'cube-today-color',
    'chart-color', 'chart-grid-color',
    'neural-node-color', 'neural-node-active-color',
    'neural-edge-color', 'neural-glow-color',
    'bg-gradient-from', 'bg-gradient-to',
    'bg-overlay',  # also accepts 'transparent' which _is_valid_color allows
    'mosaic-empty-color', 'mosaic-empty-grad-from', 'mosaic-empty-grad-to',
}

# Per-chart color keys are pulled in programmatically from the schema.
from .chart_schema import ALL_CONTROLS as _CHART_CONTROLS  # noqa: E402
for _key, _ctrl in _CHART_CONTROLS.items():
    if _ctrl['type'] == 'color':
        _COLOR_KEYS.add(_key)


# Angle: e.g. '180deg', '45deg'. We only accept integer degrees.
_ANGLE_RE = re.compile(r'^-?\d{1,3}deg$')

# Length: '0px', '12px', '0.5rem' etc. — restrictive set sufficient for blur.
_LENGTH_RE = re.compile(r'^\d{1,3}(px|rem)$')

# Filename is whatever upload_image returned: a UUID-ish hex token + ext.
# Keep this strict — the value is concatenated into a URL.
_FILENAME_RE = re.compile(r'^[a-f0-9]{16,}\.(jpg|jpeg|png|webp|gif)$', re.I)


def _is_valid_bg_type(value: str) -> bool:
    return value in ('color', 'gradient', 'image')


def _is_valid_angle(value: str) -> bool:
    return bool(isinstance(value, str) and _ANGLE_RE.match(value.strip()))


def _is_valid_filename(value: str) -> bool:
    if not isinstance(value, str):
        return False
    if value == '':
        return True
    return bool(_FILENAME_RE.match(value.strip()))


def _is_valid_length(value: str) -> bool:
    return bool(isinstance(value, str) and _LENGTH_RE.match(value.strip()))


def _is_valid_unit_interval(value: str) -> bool:
    """0..1 string."""
    try:
        f = float(value)
        return 0.0 <= f <= 1.0
    except (TypeError, ValueError):
        return False


def _is_valid_font_id(value: str) -> bool:
    from .fonts_catalog import VALID_FONT_IDS
    return value in VALID_FONT_IDS


_FONT_FILENAME_RE = re.compile(r'^[a-f0-9]{16,}\.(ttf|otf|woff|woff2)$', re.I)


def _is_valid_font_filename(value: str) -> bool:
    if not isinstance(value, str):
        return False
    if value == '':
        return True
    return bool(_FONT_FILENAME_RE.match(value.strip()))


def _is_valid_bool_str(value: str) -> bool:
    return value in ('true', 'false')


def _is_valid_mosaic_mode(value: str) -> bool:
    return value in ('color', 'gradient', 'image')


# px length restricted to 1..4 with optional decimal (e.g. '1.6px').
_LINE_WIDTH_RE = re.compile(r'^[1-4](?:\.\d)?px$')


def _is_valid_line_width(value: str) -> bool:
    return bool(isinstance(value, str) and _LINE_WIDTH_RE.match(value.strip()))




# Per-key validators. Only keys present here are accepted by /api/save.
# All callables share the same `(value: str) -> bool` signature.
_VALIDATORS = {k: _is_valid_color for k in _COLOR_KEYS}
_VALIDATORS.update({
    'bg-type':            _is_valid_bg_type,
    'bg-gradient-angle':  _is_valid_angle,
    'bg-image-filename':  _is_valid_filename,
    'bg-image-blur':      _is_valid_length,
    'bg-image-opacity':   _is_valid_unit_interval,
    'font-body-id':       _is_valid_font_id,
    'font-heading-id':    _is_valid_font_id,
    'custom-font-filename': _is_valid_font_filename,
    'notes-use-body-font': _is_valid_bool_str,
    'mosaic-enabled':         _is_valid_bool_str,
    'mosaic-filled-filename': _is_valid_filename,
    'mosaic-empty-mode':      _is_valid_mosaic_mode,
    'mosaic-empty-filename':  _is_valid_filename,
    'mosaic-empty-grad-angle': _is_valid_angle,
})

# Per-chart controls: validator inferred from `type` in the schema.
# Keeping this in sync manually with the schema is bug-prone; this
# loop derives validators from the schema, so adding a new key in
# `chart_schema.py` makes it valid at /api/save automatically.
for _ctrl in _CHART_CONTROLS.values():
    _t = _ctrl['type']
    if _t == 'color':
        _VALIDATORS[_ctrl['key']] = _is_valid_color
    elif _t == 'slider':
        _VALIDATORS[_ctrl['key']] = _is_valid_line_width
    elif _t == 'unit':
        _VALIDATORS[_ctrl['key']] = _is_valid_unit_interval

# All keys the API will accept. Anything outside is rejected.
_ALLOWED_KEYS = set(_VALIDATORS.keys())


# Section → list of keys that belong to it. Used by the per-section
# Reset endpoint and by the UI's small "reset section" links. The
# section ids match the `id` attribute of the corresponding settings
# page <section> elements.
_SECTION_KEYS = {
    'sec-bg': {
        'bg-type', 'bg-color',
        'bg-gradient-from', 'bg-gradient-to', 'bg-gradient-angle',
        'bg-image-filename', 'bg-image-blur', 'bg-image-opacity',
        'bg-overlay',
    },
    'sec-text': {
        'text-color', 'heading-color', 'brand-color',
    },
    'sec-fonts': {
        'font-body-id', 'font-heading-id',
        'custom-font-filename', 'notes-use-body-font',
    },
    'sec-calendar': {
        'cube-filled-color', 'cube-empty-color',
        'cube-border-color', 'cube-today-color',
    },
    'sec-charts-global': {
        'chart-color', 'chart-grid-color',
    },
    'sec-neural': {
        'neural-node-color', 'neural-node-active-color',
        'neural-edge-color', 'neural-glow-color',
    },
    'sec-mosaic': {
        'mosaic-enabled', 'mosaic-filled-filename',
        'mosaic-empty-mode', 'mosaic-empty-filename',
        'mosaic-empty-color',
        'mosaic-empty-grad-from', 'mosaic-empty-grad-to',
        'mosaic-empty-grad-angle',
    },
}

# Per-chart reset sections — extend programmatically from the schema
# so adding a chart automatically gets its own reset endpoint key.
from .chart_schema import CHART_SECTION_KEYS as _CHART_SECTION_KEYS  # noqa: E402
_SECTION_KEYS.update(_CHART_SECTION_KEYS)


# ── File upload config ───────────────────────────────────────

_MAX_UPLOAD_BYTES = 10 * 1024 * 1024     # 10 MB for images
_MAX_FONT_BYTES   = 5 * 1024 * 1024      # 5 MB for fonts
_ALLOWED_IMAGE_EXTS = {'.jpg', '.jpeg', '.png', '.webp', '.gif'}
_ALLOWED_FONT_EXTS  = {'.ttf', '.otf', '.woff', '.woff2'}
_BG_MAX_PIXELS = 2560  # longest side after auto-resize


def _load_row() -> UserCustomization:
    row = UserCustomization.query.first()
    if row is None:
        row = UserCustomization(settings_json='{}')
        db.session.add(row)
        db.session.commit()
    return row


def _current_settings() -> dict:
    row = _load_row()
    try:
        data = json.loads(row.settings_json or '{}')
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        return {}


# ── Pages ─────────────────────────────────────────────────────

@bp.route('/customization/')
def settings():
    """Settings page with live previews."""
    from .fonts_catalog import FONT_CATALOG
    from .chart_schema import CHARTS as CHART_SCHEMA
    current = merge_with_defaults(_current_settings())
    return render_template(
        'customization/settings.html',
        current=current,
        defaults=DEFAULTS,
        font_catalog=FONT_CATALOG,
        chart_schema=CHART_SCHEMA,
    )


# ── API ───────────────────────────────────────────────────────

@bp.route('/customization/api/save', methods=['POST'])
def api_save():
    """Merge submitted values into the saved settings.

    Each key has its own validator (see `_VALIDATORS`); unknown keys
    and invalid values are dropped and listed in `rejected`. The full
    settings blob is rewritten on every save (small enough that
    incremental patching isn't worth the complexity).
    """
    payload = request.get_json(silent=True) or {}
    if not isinstance(payload, dict):
        return jsonify({'error': 'invalid payload'}), 400

    incoming = payload.get('settings') or {}
    if not isinstance(incoming, dict):
        return jsonify({'error': 'settings must be an object'}), 400

    accepted = {}
    rejected = []
    for k, v in incoming.items():
        validator = _VALIDATORS.get(k)
        if validator is None or not validator(v):
            rejected.append(k)
            continue
        accepted[k] = v

    current = _current_settings()
    current.update(accepted)

    row = _load_row()
    row.settings_json = json.dumps(current, ensure_ascii=False)
    row.updated_at = datetime.utcnow()
    db.session.commit()

    return jsonify({
        'ok': True,
        'saved': accepted,
        'rejected': rejected,
        'settings': merge_with_defaults(current),
    })


# ── File upload / serve / delete ─────────────────────────────

@bp.route('/customization/api/upload-bg', methods=['POST'])
def api_upload_bg():
    """Accept an image upload, auto-resize, store under uploads_dir.

    Returns the saved filename. The settings UI then sets
    `bg-image-filename` to this value via /api/save. We don't auto-save
    because the user might preview multiple uploads before committing.

    Auto-resize keeps the saved file under ~2 MB / 2560px on the
    longest side — large enough to look good on 4K displays, small
    enough to not bloat the user data directory or backups.
    """
    file = request.files.get('file')
    if file is None or not file.filename:
        return jsonify({'error': 'no file'}), 400

    # Quick size check from headers (real check after read)
    raw = file.read(_MAX_UPLOAD_BYTES + 1)
    if len(raw) > _MAX_UPLOAD_BYTES:
        return jsonify({'error': 'file too large (max 10 MB)'}), 400

    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in _ALLOWED_IMAGE_EXTS:
        return jsonify({'error': 'unsupported format'}), 400

    # Try to resize via Pillow; fall back to storing as-is on import
    # error (Pillow is part of Flask deps, but be defensive).
    out_bytes = raw
    try:
        from PIL import Image
        from io import BytesIO
        img = Image.open(BytesIO(raw))
        # Strip EXIF rotation so we don't render sideways
        if hasattr(img, 'getexif'):
            from PIL import ImageOps
            img = ImageOps.exif_transpose(img)
        # Downscale if either dimension > _BG_MAX_PIXELS
        w, h = img.size
        if max(w, h) > _BG_MAX_PIXELS:
            img.thumbnail((_BG_MAX_PIXELS, _BG_MAX_PIXELS), Image.LANCZOS)
        # Encode back to original format (jpeg quality 85, otherwise default)
        buf = BytesIO()
        save_fmt = (img.format or 'JPEG').upper()
        kwargs = {}
        if save_fmt == 'JPEG':
            kwargs['quality'] = 85
            # JPEGs can't be RGBA; flatten transparent pixels onto white
            if img.mode == 'RGBA':
                from PIL import Image as _Image
                bg = _Image.new('RGB', img.size, (255, 255, 255))
                bg.paste(img, mask=img.split()[3])
                img = bg
        img.save(buf, format=save_fmt, **kwargs)
        out_bytes = buf.getvalue()
    except Exception:
        # Storage as-is is fine; we just lose auto-resize benefits.
        pass

    # Random filename keeps URL guessing impractical and avoids name
    # collisions. Single-user app, but still — clean files.
    name = secrets.token_hex(16) + ext
    out_path = uploads_dir() / name
    with open(out_path, 'wb') as f:
        f.write(out_bytes)

    return jsonify({
        'ok': True,
        'filename': name,
        'url': f'/customization/uploads/{name}',
        'bytes': len(out_bytes),
    })


@bp.route('/customization/uploads/<path:filename>')
def serve_upload(filename):
    """Serve a previously uploaded file (image or font) from uploads_dir.

    Validates the filename against the strict regex set so traversal /
    arbitrary-file reads are not possible. `secure_filename` would
    accept anything matching its (looser) rules; we want to be strict
    because this endpoint accepts an arbitrary <path:filename>.
    """
    if not (_FILENAME_RE.match(filename) or _FONT_FILENAME_RE.match(filename)):
        abort(404)
    return send_from_directory(str(uploads_dir()), filename)


# ── Font upload ──────────────────────────────────────────────

@bp.route('/customization/api/upload-font', methods=['POST'])
def api_upload_font():
    """Accept a custom font file (.ttf/.otf/.woff/.woff2, ≤ 5 MB).

    Stored under uploads_dir with a random hex filename. The settings
    UI then sets `custom-font-filename` to this value via /api/save.

    No content validation beyond extension — font files have many valid
    formats and we don't want to bundle a font parser. The browser
    will reject malformed files at @font-face load time.
    """
    file = request.files.get('file')
    if file is None or not file.filename:
        return jsonify({'error': 'no file'}), 400

    raw = file.read(_MAX_FONT_BYTES + 1)
    if len(raw) > _MAX_FONT_BYTES:
        return jsonify({'error': 'file too large (max 5 MB)'}), 400

    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in _ALLOWED_FONT_EXTS:
        return jsonify({'error': 'unsupported format'}), 400

    name = secrets.token_hex(16) + ext
    out_path = uploads_dir() / name
    with open(out_path, 'wb') as f:
        f.write(raw)

    return jsonify({
        'ok': True,
        'filename': name,
        'url': f'/customization/uploads/{name}',
        'bytes': len(raw),
    })


@bp.route('/customization/api/fonts')
def api_fonts():
    """Return the bundled-font catalog so the settings page can build
    its dropdown without hard-coding the list in two places."""
    from .fonts_catalog import FONT_CATALOG
    return jsonify({'fonts': FONT_CATALOG})


# ── Orphan cleanup ──────────────────────────────────────────

# Keys whose value is a filename inside `uploads_dir()`. Used by the
# garbage-collector to find files that are still referenced.
_UPLOAD_KEYS = (
    'bg-image-filename',
    'mosaic-filled-filename',
    'mosaic-empty-filename',
    'custom-font-filename',
)


def _scan_uploads_dir() -> list[str]:
    """Return all filenames currently living in uploads_dir().

    Restricted to files matching the upload regex set so we never risk
    deleting something the user dropped in by hand (e.g. a backup of
    their own).
    """
    import os
    out = []
    try:
        for name in os.listdir(uploads_dir()):
            if _FILENAME_RE.match(name) or _FONT_FILENAME_RE.match(name):
                out.append(name)
    except FileNotFoundError:
        pass
    return out


@bp.route('/customization/api/orphan-uploads', methods=['GET'])
def api_orphan_uploads():
    """List uploaded files NOT referenced by any saved setting.

    Read-only — the user can review the list before pressing the
    cleanup button. Useful when they've experimented with several
    background images and want to free disk space.
    """
    settings = _current_settings()
    used = {settings[k] for k in _UPLOAD_KEYS if settings.get(k)}
    all_files = _scan_uploads_dir()
    orphans = [n for n in all_files if n not in used]
    # Include byte sizes so the UI can show "free up X MB"
    import os
    total = 0
    items = []
    for name in orphans:
        try:
            sz = os.path.getsize(uploads_dir() / name)
        except OSError:
            continue
        items.append({'filename': name, 'bytes': sz})
        total += sz
    return jsonify({
        'orphans': items,
        'count': len(items),
        'total_bytes': total,
        'in_use': sorted(used),
    })


@bp.route('/customization/api/cleanup-orphans', methods=['POST'])
def api_cleanup_orphans():
    """Delete every uploaded file not referenced by a saved setting.

    Idempotent — running twice is a no-op the second time. The actual
    `os.remove` is wrapped in try/except per file so a single locked
    file doesn't abort the whole cleanup.
    """
    import os
    settings = _current_settings()
    used = {settings[k] for k in _UPLOAD_KEYS if settings.get(k)}
    deleted = []
    failed = []
    for name in _scan_uploads_dir():
        if name in used:
            continue
        try:
            os.remove(uploads_dir() / name)
            deleted.append(name)
        except OSError as exc:
            failed.append({'filename': name, 'error': str(exc)})
    return jsonify({'ok': True, 'deleted': deleted, 'failed': failed})


@bp.route('/customization/api/delete-bg', methods=['POST'])
def api_delete_bg():
    """Forget the current bg-image-filename. Does NOT delete the file
    from disk — keeping it around lets the user undo by re-saving.
    Disk cleanup is a Stage 6 concern (or manual, since the data dir
    is user-visible).
    """
    current = _current_settings()
    current['bg-image-filename'] = ''
    if current.get('bg-type') == 'image':
        current['bg-type'] = 'color'
    row = _load_row()
    row.settings_json = json.dumps(current, ensure_ascii=False)
    row.updated_at = datetime.utcnow()
    db.session.commit()
    return jsonify({'ok': True, 'settings': merge_with_defaults(current)})


@bp.route('/customization/api/reset', methods=['POST'])
def api_reset():
    """Reset all settings to defaults (clears the row's JSON blob)."""
    row = _load_row()
    row.settings_json = '{}'
    row.updated_at = datetime.utcnow()
    db.session.commit()
    return jsonify({'ok': True, 'settings': dict(DEFAULTS)})


@bp.route('/customization/api/reset-section', methods=['POST'])
def api_reset_section():
    """Reset only the keys that belong to one section.

    Body: {"section": "sec-bg"} (or any other section id from
    `_SECTION_KEYS`). Returns 400 for unknown sections so a typo in the
    UI surfaces immediately rather than silently no-op'ing.
    """
    payload = request.get_json(silent=True) or {}
    section = payload.get('section')
    keys = _SECTION_KEYS.get(section)
    if keys is None:
        return jsonify({'error': f'unknown section: {section}'}), 400

    current = _current_settings()
    removed = [k for k in keys if k in current]
    for k in keys:
        current.pop(k, None)

    row = _load_row()
    row.settings_json = json.dumps(current, ensure_ascii=False)
    row.updated_at = datetime.utcnow()
    db.session.commit()

    return jsonify({
        'ok': True,
        'section': section,
        'cleared': removed,
        'settings': merge_with_defaults(current),
    })


@bp.route('/customization/api/settings', methods=['GET'])
def api_get_settings():
    """Return the currently effective settings (defaults + overrides)."""
    return jsonify({'settings': merge_with_defaults(_current_settings())})


# ── Theme import / export ────────────────────────────────────

# Format version. Bumped when we introduce a backward-incompatible
# change in the JSON shape (currently never).
_THEME_VERSION = 1


@bp.route('/customization/api/export', methods=['GET'])
def api_export():
    """Download the current theme as a JSON file.

    Includes:
      version    — schema version of the export format
      app        — fixed string for sanity-checking the source app
      settings   — the user's overrides (NOT defaults), so the file
                   stays small and survives default changes between
                   app versions
      uploads    — any referenced upload filenames so a sister tool
                   could in future bundle the actual image bytes
                   (currently informational only)

    Returned as `application/json` with a `Content-Disposition` header
    so the browser downloads it as a file.
    """
    from flask import Response
    overrides = _current_settings()
    upload_keys = (
        'bg-image-filename', 'mosaic-filled-filename',
        'mosaic-empty-filename', 'custom-font-filename',
    )
    uploads = {k: overrides[k] for k in upload_keys if overrides.get(k)}
    payload = {
        'app': 'index.life',
        'kind': 'customization-theme',
        'version': _THEME_VERSION,
        'exported_at': datetime.utcnow().isoformat() + 'Z',
        'settings': overrides,
        'uploads': uploads,
    }
    body = json.dumps(payload, ensure_ascii=False, indent=2)
    fname = f'index-life-theme-{datetime.utcnow():%Y%m%d-%H%M%S}.json'
    return Response(
        body,
        mimetype='application/json',
        headers={
            'Content-Disposition': f'attachment; filename="{fname}"',
        },
    )


@bp.route('/customization/api/import', methods=['POST'])
def api_import():
    """Import a previously-exported theme JSON.

    Accepts the JSON body OR a `file` form field carrying the JSON.
    Each setting is run through the same per-key validator as `/save`
    — silently dropping anything invalid — so an attacker-supplied
    file can't smuggle XSS into a CSS variable.

    Note: upload filenames inside the JSON only resolve to actual
    images if those files already exist in the user's uploads dir.
    Importing on a different machine will leave bg-image / mosaic /
    custom-font filenames pointing at non-existent files; the
    customization just falls back to defaults for those keys.
    """
    data = None
    f = request.files.get('file')
    if f is not None:
        try:
            data = json.loads(f.read().decode('utf-8'))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            return jsonify({'error': f'invalid JSON: {exc}'}), 400
    else:
        data = request.get_json(silent=True)

    if not isinstance(data, dict):
        return jsonify({'error': 'invalid payload'}), 400
    if data.get('kind') != 'customization-theme':
        return jsonify({'error': 'not an index.life theme file'}), 400

    incoming = data.get('settings') or {}
    if not isinstance(incoming, dict):
        return jsonify({'error': 'settings must be an object'}), 400

    accepted = {}
    rejected = []
    for k, v in incoming.items():
        validator = _VALIDATORS.get(k)
        if validator is None or not validator(v):
            rejected.append(k)
            continue
        accepted[k] = v

    # Replace settings entirely — importing a theme should give you
    # exactly that theme, not a merge with whatever you had before.
    row = _load_row()
    row.settings_json = json.dumps(accepted, ensure_ascii=False)
    row.updated_at = datetime.utcnow()
    db.session.commit()

    return jsonify({
        'ok': True,
        'imported': list(accepted.keys()),
        'rejected': rejected,
        'settings': merge_with_defaults(accepted),
    })
