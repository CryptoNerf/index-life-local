"""
Routes for local diary application
Single-user version (no authentication)
"""
from flask import Blueprint, render_template, request, redirect, url_for, flash, make_response
from datetime import datetime, date
import calendar
from werkzeug.utils import secure_filename
from pathlib import Path
import os

from app import db
from app.models import MoodEntry, UserProfile

bp = Blueprint('main', __name__)


def allowed_file(filename, allowed_extensions):
    """Check if file extension is allowed"""
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in allowed_extensions


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

    # Get all entries for specified year
    entries = MoodEntry.query.filter(
        db.extract('year', MoodEntry.date) == year
    ).all()

    # Create set of filled days for quick lookup
    filled_days = {e.date for e in entries}

    # Build calendar data for all 12 months
    months = []
    for month_num in range(1, 13):
        days_in_month = calendar.monthrange(year, month_num)[1]
        days = []
        for day in range(1, days_in_month + 1):
            d = date(year, month_num, day)
            days.append({
                'date': d,
                'filled': d in filled_days
            })
        months.append({
            'number': month_num,
            'name': calendar.month_name[month_num],
            'days': days
        })

    # Get all available years for navigation
    all_years = db.session.query(
        db.extract('year', MoodEntry.date).label('year')
    ).distinct().order_by(db.text('year DESC')).all()
    available_years = [int(y.year) for y in all_years]

    # Add current year if not in list
    current_year = date.today().year
    if current_year not in available_years:
        available_years.insert(0, current_year)
        available_years.sort(reverse=True)

    today = date.today()
    return render_template('mood_grid.html',
                         months=months,
                         today=today,
                         year=year,
                         available_years=available_years,
                         current_year=current_year)


@bp.route('/day/<string:day>', methods=['GET', 'POST'])
def edit_day(day):
    """Edit or create mood entry for specific day"""
    try:
        day_date = datetime.strptime(day, "%Y-%m-%d").date()
    except ValueError:
        flash('Invalid date format', 'error')
        return redirect(url_for('main.mood_grid'))

    # Get existing entry or None
    entry = MoodEntry.query.filter_by(date=day_date).first()
    is_new = entry is None

    if request.method == 'POST':
        rating = request.form.get('rating', type=int)
        note = request.form.get('note', '').strip()

        # Validate rating
        if rating is None or not (1 <= rating <= 10):
            flash('Rating must be between 1 and 10', 'error')
            return redirect(url_for('main.edit_day', day=day))

        if entry:
            # Update existing entry
            entry.rating = rating
            entry.note = note
            entry.updated_at = datetime.utcnow()
        else:
            # Create new entry
            entry = MoodEntry(
                date=day_date,
                rating=rating,
                note=note
            )
            db.session.add(entry)

        try:
            db.session.commit()
            # Redirect to the year of the edited entry (no flash message needed - visual confirmation on calendar is enough)
            return redirect(url_for('main.mood_grid', year=day_date.year))
        except Exception as e:
            db.session.rollback()
            flash(f'Error saving entry: {e}', 'error')

    return render_template('edit_day.html',
                         day=day_date,
                         entry=entry,
                         is_new=is_new,
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

    # Get all years with entries for archive
    all_years = db.session.query(
        db.extract('year', MoodEntry.date).label('year')
    ).distinct().order_by(db.text('year DESC')).all()
    archive_years = [int(y.year) for y in all_years]

    # Get entry count for each year
    year_stats = {}
    for year in archive_years:
        count = MoodEntry.query.filter(
            db.extract('year', MoodEntry.date) == year
        ).count()
        year_stats[year] = count

    if request.method == 'POST':
        # Update profile information
        profile.username = request.form.get('username', 'User')
        profile.email = request.form.get('email', '')

        # Handle photo upload
        if 'photo' in request.files:
            file = request.files['photo']
            if file and file.filename:
                from flask import current_app
                if allowed_file(file.filename, current_app.config['ALLOWED_EXTENSIONS']):
                    # Delete old photo if exists
                    if profile.photo_filename:
                        old_photo_path = Path(current_app.config['UPLOAD_FOLDER']) / profile.photo_filename
                        if old_photo_path.exists():
                            old_photo_path.unlink()

                    # Save new photo
                    filename = secure_filename(file.filename)
                    # Add timestamp to avoid conflicts
                    name, ext = os.path.splitext(filename)
                    filename = f"{name}_{int(datetime.now().timestamp())}{ext}"

                    filepath = Path(current_app.config['UPLOAD_FOLDER']) / filename
                    file.save(str(filepath))
                    profile.photo_filename = filename
                else:
                    flash('Invalid file type. Allowed: png, jpg, jpeg, gif', 'error')

        try:
            db.session.commit()
            flash('Profile updated successfully!', 'success')
            return redirect(url_for('main.account'))
        except Exception as e:
            db.session.rollback()
            flash(f'Error updating profile: {e}', 'error')

    return render_template('account.html',
                         profile=profile,
                         archive_years=archive_years,
                         year_stats=year_stats,
                         current_year=date.today().year)


@bp.route('/what_is_index')
def what_is_index():
    """Information page about the application"""
    return render_template('what_is_index.html',
                         current_year=date.today().year)


@bp.route('/stats')
def stats():
    """Statistics page"""
    profile = UserProfile.query.first()
    entries = MoodEntry.query.order_by(MoodEntry.date.desc()).all()

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


@bp.route('/export/markdown')
def export_markdown():
    """Export all diary entries to Markdown format"""
    # Get user profile
    profile = UserProfile.query.first()
    username = profile.username if profile else 'User'

    # Get all entries sorted by date (newest first)
    entries = MoodEntry.query.order_by(MoodEntry.date.desc()).all()

    if not entries:
        flash('No entries to export', 'error')
        return redirect(url_for('main.account'))

    # Build Markdown content
    markdown_lines = []
    markdown_lines.append(f"# {username}'s Mood Diary")
    markdown_lines.append("")
    markdown_lines.append(f"**Total Entries:** {len(entries)}")
    if profile:
        markdown_lines.append(f"**Average Mood:** {profile.avg_rating}/10")
    markdown_lines.append(f"**Exported:** {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    markdown_lines.append("")
    markdown_lines.append("---")
    markdown_lines.append("")

    # Group entries by year and month
    current_year = None
    current_month = None

    for entry in entries:
        entry_year = entry.date.year
        entry_month = entry.date.month

        # Add year header if changed
        if entry_year != current_year:
            markdown_lines.append("")
            markdown_lines.append(f"## {entry_year}")
            markdown_lines.append("")
            current_year = entry_year
            current_month = None

        # Add month header if changed
        if entry_month != current_month:
            month_name = calendar.month_name[entry_month]
            markdown_lines.append(f"### {month_name}")
            markdown_lines.append("")
            current_month = entry_month

        # Add entry
        day_str = entry.date.strftime('%Y-%m-%d, %A')
        markdown_lines.append(f"#### {day_str}")
        markdown_lines.append("")
        markdown_lines.append(f"**Mood Rating:** {entry.rating}/10")
        markdown_lines.append("")

        if entry.note and entry.note.strip():
            markdown_lines.append(entry.note.strip())
            markdown_lines.append("")

        markdown_lines.append("---")
        markdown_lines.append("")

    # Create response with file download
    markdown_content = '\n'.join(markdown_lines)

    response = make_response(markdown_content)
    response.headers['Content-Type'] = 'text/markdown; charset=utf-8'
    response.headers['Content-Disposition'] = f'attachment; filename=mood_diary_{datetime.now().strftime("%Y%m%d_%H%M%S")}.md'

    return response
