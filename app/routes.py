# index.life — Local mood diary
# https://github.com/CryptoNerf/index-life-local
# Copyright (C) 2026 Émile Alexanyan
#
# Licensed under AGPL-3.0 with additional terms per Section 7
# (preservation of author attribution, no misrepresentation of
# origin). See LICENSE and COPYRIGHT at the root of this project.
"""
Routes for local diary application
Single-user version (no authentication)
"""
from flask import Blueprint, render_template, request, redirect, url_for, flash, make_response, send_from_directory, current_app
from datetime import datetime, date, timedelta
from app.timeutil import utcnow
import calendar
import logging
from werkzeug.utils import secure_filename
from pathlib import Path
import os
import re

from app import db
from app.i18n import t
from app.models import MoodEntry, UserProfile, SyncMeta

log = logging.getLogger(__name__)

bp = Blueprint('main', __name__)


@bp.route('/profile_photos/<filename>')
def profile_photo(filename):
    """Serve profile photos from the data directory."""
    upload_dir = Path(current_app.config['UPLOAD_FOLDER'])
    return send_from_directory(upload_dir, filename)


def allowed_file(filename, allowed_extensions):
    """Check if file extension is allowed"""
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in allowed_extensions


def normalize_note(note):
    """Normalize markdown saved from the editor to avoid blank lines."""
    if not note:
        return ''

    cleaned = note.replace('\r\n', '\n').replace('\r', '\n')
    cleaned = cleaned.replace('\u00a0', ' ')
    cleaned = re.sub(r'[\u200B-\u200D\uFEFF]', '', cleaned)

    # Collapse blank lines between list items (ordered or unordered)
    cleaned = re.sub(
        r'(^\s*(?:-|\d+\.)\s+.*)\n\s*\n(?=\s*(?:-|\d+\.)\s+)',
        r'\1\n',
        cleaned,
        flags=re.MULTILINE
    )

    cleaned = renumber_ordered_lists(cleaned)

    # Collapse runs of 2+ blank lines into a single blank line,
    # but keep structural blank lines that Markdown needs (around
    # blockquotes, headings, horizontal rules, etc.).
    cleaned = re.sub(r'\n{3,}', '\n\n', cleaned)

    lines = cleaned.split('\n')
    output = []
    in_fence = False

    for line in lines:
        if line.strip().startswith('```'):
            in_fence = not in_fence
            output.append(line.strip())
            continue

        if in_fence:
            output.append(line.rstrip())
            continue

        stripped = line.strip()

        # Keep blank lines that separate block-level elements
        if not stripped:
            # Avoid leading blank lines or consecutive blank lines
            if output and output[-1] != '':
                output.append('')
            continue

        output.append(line.rstrip())

    # Remove trailing blank line(s)
    while output and output[-1] == '':
        output.pop()

    return '\n'.join(output).strip()


def renumber_ordered_lists(text):
    """Renumber ordered list items to 1..n within each contiguous list block."""
    lines = text.split('\n')
    output = []
    in_list = False
    current_indent = ''
    counter = 1

    for line in lines:
        match = re.match(r'^(\s*)(\d+)\.\s+(.*)$', line)
        if match:
            indent = match.group(1) or ''
            content = match.group(3)
            if not in_list or indent != current_indent:
                in_list = True
                current_indent = indent
                counter = 1
            output.append(f"{indent}{counter}. {content}")
            counter += 1
            continue

        in_list = False
        current_indent = ''
        counter = 1
        output.append(line)

    return '\n'.join(output)


@bp.route('/')
def index():
    """Redirect to mood grid"""
    return redirect(url_for('main.mood_grid'))


@bp.route('/calendar')
@bp.route('/calendar/<int:year>')
@bp.route('/mood_grid')
@bp.route('/mood_grid/<int:year>')
def mood_grid(year=None):
    """Display calendar grid with all mood entries for specified year"""
    # If no year specified, use current year
    if year is None:
        year = date.today().year

    # Get all entries for specified year (exclude soft-deleted tombstones)
    entries = MoodEntry.query.filter(
        db.extract('year', MoodEntry.date) == year,
        MoodEntry.deleted == False,  # noqa: E712
    ).all()

    # Create set of filled days for quick lookup
    filled_days = {e.date for e in entries}
    # …and the rating itself, for the optional "colour the day by its rating"
    # mode in the customization module (plain filled/empty ignores it).
    ratings = {e.date: e.rating for e in entries}

    # Build calendar data for all 12 months
    months = []
    for month_num in range(1, 13):
        days_in_month = calendar.monthrange(year, month_num)[1]
        days = []
        for day in range(1, days_in_month + 1):
            d = date(year, month_num, day)
            days.append({
                'date': d,
                'filled': d in filled_days,
                'rating': ratings.get(d),
            })
        months.append({
            'number': month_num,
            'name': calendar.month_name[month_num],
            'days': days
        })

    # Get all available years for navigation
    all_years = db.session.query(
        db.extract('year', MoodEntry.date).label('year')
    ).filter(MoodEntry.deleted == False).distinct(  # noqa: E712
    ).order_by(db.text('year DESC')).all()
    available_years = [int(y.year) for y in all_years]

    # Add current year if not in list
    current_year = date.today().year
    if current_year not in available_years:
        available_years.insert(0, current_year)
        available_years.sort(reverse=True)

    # If requested year doesn't exist (e.g., last entry was deleted), redirect to current year
    if year != current_year and year not in available_years:
        return redirect(url_for('main.mood_grid', year=current_year))

    today = date.today()
    return render_template('mood_grid.html',
                         months=months,
                         today=today,
                         year=year,
                         available_years=available_years,
                         current_year=current_year)


@bp.route('/day/<string:day>/delete', methods=['POST'])
def delete_day(day):
    """Delete mood entry for specific day"""
    try:
        day_date = datetime.strptime(day, "%Y-%m-%d").date()
    except ValueError:
        flash(t('flash.invalid_date'), 'error')
        return redirect(url_for('main.mood_grid'))

    entry = MoodEntry.query.filter_by(date=day_date).first()

    if entry:
        entry_year = entry.date.year
        try:
            # Soft-delete only. The tombstone (deleted=True) stays in the
            # DB so the deletion propagates to every other device via the
            # snapshot — a hard-delete would let a peer that still has the
            # entry resurrect it on the next merge. Tombstones are hidden
            # from the UI by the deleted=False filter on read queries.
            entry.deleted = True
            entry.updated_at = utcnow()
            db.session.commit()

            # Push the deletion to shared storage right away (best-effort).
            try:
                from app.sync import is_sync_configured, export_now
                if is_sync_configured():
                    export_now(current_app._get_current_object())
            except Exception:
                log.warning('Immediate sync push failed; periodic sync will retry',
                            exc_info=True)

            return redirect(url_for('main.mood_grid', year=entry_year))
        except Exception as e:
            db.session.rollback()
            flash(t('flash.entry_delete_error', err=e), 'error')
            return redirect(url_for('main.edit_day', day=day))
    else:
        return redirect(url_for('main.mood_grid'))


@bp.route('/day/<string:day>', methods=['GET', 'POST'])
def edit_day(day):
    """Edit or create mood entry for specific day"""
    try:
        day_date = datetime.strptime(day, "%Y-%m-%d").date()
    except ValueError:
        flash(t('flash.invalid_date'), 'error')
        return redirect(url_for('main.mood_grid'))

    # Get existing entry or None
    entry = MoodEntry.query.filter_by(date=day_date).first()
    is_new = entry is None

    if request.method == 'POST':
        rating = request.form.get('rating', type=int)
        note = normalize_note(request.form.get('note', ''))

        # Validate rating - MUST be provided
        if rating is None or not (1 <= rating <= 10):
            flash(t('flash.rating_required'), 'error')
            return redirect(url_for('main.edit_day', day=day))

        # Get device_id for sync
        device_id_row = db.session.get(SyncMeta, 'device_id')
        _device_id = device_id_row.value if device_id_row else None

        # Apply changes inside the retry loop so that a rollback (which
        # detaches new objects / reverts attribute changes) is recovered
        # before the next attempt. Without this, the second commit() after
        # a rollback is a silent no-op — saved=True is set but nothing
        # was written, and entry.id is left as None, which downstream
        # code (process_entry_async) cannot handle.
        import time as _time
        saved = False
        last_exc = None
        for _attempt in range(4):
            try:
                if is_new:
                    # Re-fetch on retry in case a concurrent writer created it
                    existing = MoodEntry.query.filter_by(date=day_date).first()
                    if existing is None:
                        entry = MoodEntry(
                            date=day_date,
                            rating=rating,
                            note=note,
                            device_id=_device_id,
                        )
                        db.session.add(entry)
                    else:
                        entry = existing
                        entry.rating = rating
                        entry.note = note
                        entry.deleted = False  # revive a tombstone if present
                        entry.updated_at = utcnow()
                        if _device_id:
                            entry.device_id = _device_id
                else:
                    entry = MoodEntry.query.filter_by(date=day_date).first()
                    if entry is None:
                        # Edge case: entry was deleted between GET and POST
                        entry = MoodEntry(
                            date=day_date,
                            rating=rating,
                            note=note,
                            device_id=_device_id,
                        )
                        db.session.add(entry)
                    else:
                        entry.rating = rating
                        entry.note = note
                        entry.deleted = False  # revive a tombstone if present
                        entry.updated_at = utcnow()
                        if _device_id:
                            entry.device_id = _device_id

                db.session.commit()
                saved = True
                break
            except Exception as e:
                db.session.rollback()
                if 'locked' in str(e).lower() and _attempt < 3:
                    _time.sleep(0.4 * (_attempt + 1))
                    continue
                last_exc = e
                break

        if not saved:
            flash(t('flash.entry_save_error', err=last_exc), 'error')
        else:
            # Trigger background processing if assistant module is active
            from flask import current_app
            if 'assistant' in current_app.config.get('ACTIVE_MODULES', []):
                try:
                    from app.modules.assistant.background import process_entry_async
                    process_entry_async(current_app._get_current_object(), entry.id)
                except ImportError:
                    pass

            if 'deep_mind' in current_app.config.get('ACTIVE_MODULES', []):
                try:
                    # Automatic (debounced): a full re-cluster + LLM rename of
                    # every topic is expensive, so analyze_async throttles
                    # post-save runs. The neural map's "Analyze" button forces
                    # an immediate rebuild.
                    from app.modules.deep_mind.background import analyze_async
                    analyze_async(current_app._get_current_object())
                except ImportError:
                    pass

            # Record that day's weather (best-effort, only if the user opted
            # in). One Open-Meteo call covers the entry day + the prior week,
            # so gaps from days the app wasn't opened heal themselves.
            try:
                from app import signals
                if signals.is_weather_enabled():
                    from datetime import timedelta as _td
                    signals.record_weather_async(
                        current_app._get_current_object(),
                        day_date - _td(days=6), day_date)
            except Exception:
                log.warning('Weather trigger failed', exc_info=True)

            # Push our snapshot to shared storage (if configured)
            try:
                from app.sync import is_sync_configured, export_now
                if is_sync_configured():
                    export_now(current_app._get_current_object())
            except Exception:
                log.warning('Immediate sync push failed; periodic sync will retry',
                            exc_info=True)

            return redirect(url_for('main.mood_grid', year=day_date.year))

    # A soft-deleted day shows an empty form (the tombstone is invisible
    # to the user; saving will revive the row).
    display_entry = None if (entry and entry.deleted) else entry
    return render_template('edit_day.html',
                         day=day_date,
                         entry=display_entry,
                         is_new=display_entry is None,
                         current_year=date.today().year)


@bp.route('/account', methods=['GET', 'POST'])
def account():
    """User profile and settings"""
    profile = UserProfile.query.first()

    if not profile:
        # Create default profile if doesn't exist
        profile = UserProfile(username='User', email='')
        db.session.add(profile)
        db.session.commit()

    # Get all years with entries for archive (exclude soft-deleted)
    all_years = db.session.query(
        db.extract('year', MoodEntry.date).label('year')
    ).filter(MoodEntry.deleted == False).distinct(  # noqa: E712
    ).order_by(db.text('year DESC')).all()
    archive_years = [int(y.year) for y in all_years]

    # Get entry count for each year
    year_stats = {}
    for year in archive_years:
        count = MoodEntry.query.filter(
            db.extract('year', MoodEntry.date) == year,
            MoodEntry.deleted == False,  # noqa: E712
        ).count()
        year_stats[year] = count

    if request.method == 'POST':
        # Update profile information
        profile.username = request.form.get('username', 'User')
        profile.email = request.form.get('email', '')

        # Handle birthdate
        birthdate_str = request.form.get('birthdate', '').strip()
        if birthdate_str:
            try:
                profile.birthdate = datetime.strptime(birthdate_str, '%Y-%m-%d').date()
            except ValueError:
                flash(t('flash.invalid_birthdate'), 'error')
        else:
            profile.birthdate = None

        # Handle photo upload
        if 'photo' in request.files:
            file = request.files['photo']
            if file and file.filename:
                from flask import current_app
                if allowed_file(file.filename, current_app.config['ALLOWED_EXTENSIONS']):
                    # Delete old photo if exists. Best-effort: a locked or
                    # permission-blocked file must not turn a profile save
                    # into a 500 — the new photo still replaces it in the UI.
                    if profile.photo_filename:
                        old_photo_path = Path(current_app.config['UPLOAD_FOLDER']) / profile.photo_filename
                        try:
                            if old_photo_path.exists():
                                old_photo_path.unlink()
                        except OSError as exc:
                            log.warning('Could not delete old photo %s: %s',
                                        old_photo_path, exc)

                    # Save new photo
                    filename = secure_filename(file.filename)
                    # Add timestamp to avoid conflicts
                    name, ext = os.path.splitext(filename)
                    filename = f"{name}_{int(datetime.now().timestamp())}{ext}"

                    filepath = Path(current_app.config['UPLOAD_FOLDER']) / filename
                    file.save(str(filepath))
                    profile.photo_filename = filename
                else:
                    flash(t('flash.invalid_file_type'), 'error')

        try:
            db.session.commit()
            flash(t('flash.profile_updated'), 'success')
            return redirect(url_for('main.account'))
        except Exception as e:
            db.session.rollback()
            flash(t('flash.profile_update_error', err=e), 'error')

    from app import signals
    return render_template('account.html',
                         profile=profile,
                         archive_years=archive_years,
                         year_stats=year_stats,
                         weather_enabled=signals.is_weather_enabled(),
                         weather_location=signals.get_weather_location(),
                         current_year=date.today().year)


def _safe_next(default_endpoint='main.account'):
    """Resolve the post-action redirect target.

    Honours a `next` form field but only when it's a same-app relative path
    (starts with a single '/'), so the weather form on the chart page can
    return there without opening a redirect to an external site.
    """
    nxt = (request.form.get('next') or '').strip()
    if nxt.startswith('/') and not nxt.startswith('//'):
        return nxt
    return url_for(default_endpoint)


@bp.route('/account/weather', methods=['POST'])
def set_weather():
    """Enable/disable the weather integration and set its location.

    Server-side flow (no JS): the user types a city, we geocode it via
    Open-Meteo, store lat/lon, and kick off a one-month backfill so the
    mood↔weather link has data right away. Can be submitted from the account
    page or from the weather chart page (via a `next` field).
    """
    from app import signals
    from app.i18n import t, get_current_lang

    back = _safe_next()

    if request.form.get('action') == 'disable':
        signals.set_weather_config(False)
        flash(t('weather.disabled'), 'success')
        return redirect(back)

    city = (request.form.get('city') or '').strip()
    if not city:
        flash(t('weather.need_city'), 'error')
        return redirect(back)

    # Geocode in the user's UI language so Cyrillic city names resolve.
    loc = signals.geocode_city(city, lang=get_current_lang())
    if not loc:
        flash(t('weather.not_found', city=city), 'error')
        return redirect(back)

    signals.set_weather_config(True, lat=loc['lat'], lon=loc['lon'],
                               label=loc['label'])
    # Backfill weather across the whole journaled history so the correlation
    # covers every existing day, not just dates after enabling.
    signals.backfill_all_weather_async(current_app._get_current_object())
    flash(t('weather.enabled', location=loc['label']), 'success')
    return redirect(back)


@bp.route('/account/weather/backfill', methods=['POST'])
def weather_backfill():
    """Re-fetch weather for the full diary history (for users who enabled
    weather before this existed, or to fill gaps). Background + non-blocking."""
    from app import signals
    from app.i18n import t

    back = _safe_next()
    if not (signals.is_weather_enabled() and signals.get_weather_location()):
        flash(t('weather.need_enable_first'), 'error')
        return redirect(back)
    signals.backfill_all_weather_async(current_app._get_current_object())
    flash(t('weather.backfill_started'), 'success')
    return redirect(back)


@bp.route('/account/language', methods=['POST'])
def set_language():
    """Save the user's interface language preference.

    Single-user app: writes the new code straight onto the
    UserProfile row. The i18n context processor reads it on the next
    request render, so a redirect back to /account is enough.
    """
    from app.i18n import SUPPORTED_LANGS
    lang = (request.form.get('language') or '').strip().lower()
    if lang not in SUPPORTED_LANGS:
        flash(t('flash.language_unsupported'), 'error')
        return redirect(url_for('main.account'))

    profile = UserProfile.query.first()
    if profile is None:
        profile = UserProfile(username='User', email='')
        db.session.add(profile)
    profile.language = lang
    try:
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        flash(t('flash.language_save_error', err=exc), 'error')
    return redirect(url_for('main.account'))


@bp.route('/what_is_index')
def what_is_index():
    """Information page about the application"""
    return render_template('what_is_index.html',
                         current_year=date.today().year)


@bp.route('/stats')
def stats():
    """Statistics page"""
    profile = UserProfile.query.first()
    entries = MoodEntry.query.filter(MoodEntry.deleted == False).order_by(MoodEntry.date.desc()).all()  # noqa: E712

    # Calculate stats
    total_entries = len(entries)
    avg_rating = profile.avg_rating if profile else 0

    # Monthly stats for current year
    year = date.today().year
    monthly_stats = {}
    for month in range(1, 13):
        month_entries = [e for e in entries if e.date.year == year and e.date.month == month]
        if month_entries:
            monthly_avg = sum(e.rating for e in month_entries) / len(month_entries)
            monthly_stats[month] = {
                'count': len(month_entries),
                'avg': round(monthly_avg, 1)
            }

    return render_template('stats.html',
                         total_entries=total_entries,
                         avg_rating=avg_rating,
                         monthly_stats=monthly_stats,
                         year=year)


@bp.route('/life')
def life_calendar():
    """Life in weeks calendar page"""
    profile = UserProfile.query.first()
    birthdate = profile.birthdate if profile else None

    weeks_lived = None
    current_week_index = None

    if birthdate:
        today = date.today()
        if birthdate <= today:
            days = (today - birthdate).days
            weeks_lived = days // 7
            current_week_index = min(weeks_lived, 80 * 52 - 1)

    show_change_form = 'change' in request.args

    return render_template('life_calendar.html',
                           birthdate=birthdate,
                           weeks_lived=weeks_lived,
                           current_week_index=current_week_index,
                           show_change_form=show_change_form,
                           current_year=date.today().year)


@bp.route('/life/set-birthdate', methods=['POST'])
def life_set_birthdate():
    """Save birthdate from the life calendar prompt form.

    Form fields are three separate selects (birthdate_day/month/year) —
    locale-independent — combined here into a date. The legacy single
    `birthdate` field (YYYY-MM-DD) is still accepted for compatibility.
    """
    bd = None
    legacy_str = request.form.get('birthdate', '').strip()
    if legacy_str:
        try:
            bd = datetime.strptime(legacy_str, '%Y-%m-%d').date()
        except ValueError:
            flash(t('flash.invalid_date'), 'error')
            return redirect(url_for('main.life_calendar'))
    else:
        d = request.form.get('birthdate_day', '').strip()
        m = request.form.get('birthdate_month', '').strip()
        y = request.form.get('birthdate_year', '').strip()
        if d and m and y:
            try:
                bd = date(int(y), int(m), int(d))
            except ValueError:
                flash(t('flash.invalid_birthdate_combo'), 'error')
                return redirect(url_for('main.life_calendar'))
    if bd:

        profile = UserProfile.query.first()
        if not profile:
            profile = UserProfile(username='User', email='')
            db.session.add(profile)

        profile.birthdate = bd
        try:
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            flash(t('flash.birthdate_save_error', err=e), 'error')

    return redirect(url_for('main.life_calendar'))


def _build_markdown_export() -> tuple[str, str] | None:
    """Render the full diary as a single Markdown document.

    Returns (content, suggested_filename) or None when the diary is empty.
    Split out from the HTTP endpoint so the JSON API + pywebview save
    flow can reuse it without duplicating the layout logic.
    """
    profile = UserProfile.query.first()
    username = profile.username if profile else 'User'
    entries = MoodEntry.query.filter(MoodEntry.deleted == False).order_by(MoodEntry.date.desc()).all()  # noqa: E712
    if not entries:
        return None

    lines = []
    lines.append(f"# {username}'s Mood Diary")
    lines.append("")
    lines.append(f"**Total Entries:** {len(entries)}")
    if profile:
        lines.append(f"**Average Mood:** {profile.avg_rating}/10")
    lines.append(f"**Exported:** {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append("")
    lines.append("---")
    lines.append("")

    current_year = None
    current_month = None
    for entry in entries:
        if entry.date.year != current_year:
            lines.append("")
            lines.append(f"## {entry.date.year}")
            lines.append("")
            current_year = entry.date.year
            current_month = None
        if entry.date.month != current_month:
            lines.append(f"### {calendar.month_name[entry.date.month]}")
            lines.append("")
            current_month = entry.date.month
        lines.append(f"#### {entry.date.strftime('%Y-%m-%d, %A')}")
        lines.append("")
        lines.append(f"**Mood Rating:** {entry.rating}/10")
        lines.append("")
        if entry.note and entry.note.strip():
            lines.append(entry.note.strip())
            lines.append("")
        lines.append("---")
        lines.append("")

    filename = f'mood_diary_{datetime.now().strftime("%Y%m%d_%H%M%S")}.md'
    return '\n'.join(lines), filename


@bp.route('/api/export/markdown')
def api_export_markdown():
    """Return the markdown export as JSON.

    Used by the account-page Export button so the front-end can route
    the content through pywebview's native save dialog (the HTTP
    download path doesn't work inside WKWebView — Content-Disposition
    is ignored and the file renders inline with no way back).
    """
    from flask import jsonify
    result = _build_markdown_export()
    if result is None:
        return jsonify({'error': 'No entries to export'}), 404
    content, filename = result
    return jsonify({'content': content, 'filename': filename})


@bp.route('/export/markdown')
def export_markdown():
    """HTTP-download fallback for the markdown export.

    Kept for environments without pywebview (running in a regular
    browser). The native-app account button targets
    `/api/export/markdown` instead and bridges to a save dialog.
    """
    result = _build_markdown_export()
    if result is None:
        flash(t('flash.no_entries_export'), 'error')
        return redirect(url_for('main.account'))
    content, filename = result
    response = make_response(content)
    response.headers['Content-Type'] = 'text/markdown; charset=utf-8'
    response.headers['Content-Disposition'] = f'attachment; filename={filename}'
    return response
