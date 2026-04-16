"""
Insights — landing with visualization cards + detail pages.
"""
import math
from datetime import date, timedelta
from collections import Counter

from flask import render_template, redirect, url_for

from app import db
from app.models import MoodEntry
from . import bp


# ── Data helpers ────────────────────────────────────────────

def _monthly_averages(year: int):
    entries = MoodEntry.query.filter(
        db.extract('year', MoodEntry.date) == year
    ).all()
    buckets = [[] for _ in range(12)]
    for e in entries:
        buckets[e.date.month - 1].append(e.rating)
    return [
        (round(sum(b) / len(b), 2) if b else None)
        for b in buckets
    ]


def _distribution(year: int):
    entries = MoodEntry.query.filter(
        db.extract('year', MoodEntry.date) == year
    ).all()
    c = Counter(e.rating for e in entries)
    return [c.get(i, 0) for i in range(1, 11)]


def _year_heatmap(year: int, cell: int = 14, gap: int = 3):
    entries = {
        e.date: e.rating
        for e in MoodEntry.query.filter(
            db.extract('year', MoodEntry.date) == year
        ).all()
    }

    jan1 = date(year, 1, 1)
    grid_start = jan1 - timedelta(days=jan1.weekday())
    dec31 = date(year, 12, 31)
    total_weeks = (dec31 - grid_start).days // 7 + 1

    today = date.today()
    cells = []
    for w in range(total_weeks):
        for d in range(7):
            cur = grid_start + timedelta(weeks=w, days=d)
            cells.append({
                'x': w * (cell + gap),
                'y': d * (cell + gap),
                'rating': entries.get(cur),
                'date': cur,
                'in_year': cur.year == year,
                'is_today': cur == today,
            })

    month_labels = []
    seen = set()
    for w in range(total_weeks):
        for d in range(7):
            cur = grid_start + timedelta(weeks=w, days=d)
            if cur.year == year and cur.day <= 7 and cur.month not in seen:
                month_labels.append({
                    'x': w * (cell + gap),
                    'label': '%02d' % cur.month,
                })
                seen.add(cur.month)
                break

    return {
        'cells': cells,
        'month_labels': month_labels,
        'cell': cell,
        'gap': gap,
        'grid_w': total_weeks * (cell + gap) - gap,
        'grid_h': 7 * (cell + gap) - gap,
        'total_weeks': total_weeks,
    }


def _available_years(today):
    rows = db.session.query(
        db.extract('year', MoodEntry.date).label('y')
    ).distinct().order_by(db.text('y DESC')).all()
    years = [int(r.y) for r in rows]
    if today.year not in years:
        years.insert(0, today.year)
        years.sort(reverse=True)
    return years


# ── Routes ──────────────────────────────────────────────────

@bp.route('/insights')
def insights_page():
    today = date.today()
    # Mini preview for "overview" card: a tiny heatmap of current year
    preview = _year_heatmap(today.year, cell=6, gap=2)
    return render_template(
        'insights/insights_landing.html',
        preview_heat=preview,
        current_year=today.year,
    )


@bp.route('/insights/overview')
@bp.route('/insights/overview/<int:year>')
def overview(year=None):
    today = date.today()
    if year is None:
        year = today.year

    available_years = _available_years(today)
    if year != today.year and year not in available_years:
        return redirect(url_for('insights.overview', year=today.year))

    heat = _year_heatmap(year)
    heat_pad_l = 34
    heat_pad_t = 24
    heat_svg_w = heat['grid_w'] + heat_pad_l + 12
    heat_svg_h = heat['grid_h'] + heat_pad_t + 12

    # Monthly averages — full-width
    month_avgs = _monthly_averages(year)
    bars_w, bars_h = 1040, 380
    bars_pad_l, bars_pad_r, bars_pad_t, bars_pad_b = 60, 24, 36, 48
    bars_plot_w = bars_w - bars_pad_l - bars_pad_r
    bars_plot_h = bars_h - bars_pad_t - bars_pad_b
    slot_w = bars_plot_w / 12
    bar_w = slot_w * 0.5
    monthly_bars = []
    for i, v in enumerate(month_avgs):
        cx = bars_pad_l + slot_w * (i + 0.5)
        if v is None:
            monthly_bars.append({'x': cx - bar_w/2, 'w': bar_w, 'h': 0,
                                 'y': bars_pad_t + bars_plot_h, 'v': None, 'label': i+1})
        else:
            h = v / 10 * bars_plot_h
            monthly_bars.append({
                'x': cx - bar_w/2, 'w': bar_w, 'h': h,
                'y': bars_pad_t + bars_plot_h - h,
                'v': v, 'label': i+1,
            })

    # Distribution — full-width
    dist = _distribution(year)
    dist_max = max(dist) if any(dist) else 1
    dist_w, dist_h = 1040, 380
    dist_pad_l, dist_pad_r, dist_pad_t, dist_pad_b = 44, 24, 36, 48
    dist_plot_w = dist_w - dist_pad_l - dist_pad_r
    dist_plot_h = dist_h - dist_pad_t - dist_pad_b
    dslot_w = dist_plot_w / 10
    dbar_w = dslot_w * 0.55
    dist_bars = []
    for i, c in enumerate(dist):
        cx = dist_pad_l + dslot_w * (i + 0.5)
        h = (c / dist_max) * dist_plot_h if dist_max else 0
        dist_bars.append({
            'x': cx - dbar_w/2, 'w': dbar_w, 'h': h,
            'y': dist_pad_t + dist_plot_h - h,
            'v': c, 'label': i+1,
        })

    all_entries = MoodEntry.query.filter(
        db.extract('year', MoodEntry.date) == year
    ).all()
    ratings = [e.rating for e in all_entries]
    total = len(ratings)
    avg = round(sum(ratings)/total, 2) if total else None

    return render_template(
        'insights/insights_overview.html',
        year=year,
        current_year=today.year,
        available_years=available_years,
        total=total, avg=avg,
        heat=heat,
        heat_pad_l=heat_pad_l, heat_pad_t=heat_pad_t,
        heat_svg_w=heat_svg_w, heat_svg_h=heat_svg_h,
        bars_w=bars_w, bars_h=bars_h,
        bars_pad_l=bars_pad_l, bars_pad_t=bars_pad_t,
        bars_plot_h=bars_plot_h,
        monthly_bars=monthly_bars,
        bars_baseline_y=bars_pad_t + bars_plot_h,
        dist_w=dist_w, dist_h=dist_h,
        dist_pad_l=dist_pad_l,
        dist_bars=dist_bars,
        dist_baseline_y=dist_pad_t + dist_plot_h,
    )


def _year_series(year: int):
    """Return sorted list of (day_of_year, rating, date) for the year."""
    entries = MoodEntry.query.filter(
        db.extract('year', MoodEntry.date) == year
    ).order_by(MoodEntry.date.asc()).all()
    return [(e.date.timetuple().tm_yday, e.rating, e.date) for e in entries]


def _days_in_year(year: int) -> int:
    return 366 if (year % 4 == 0 and year % 100 != 0) or (year % 400 == 0) else 365


# ── River of mood ────────────────────────────────────────────

@bp.route('/insights/river')
@bp.route('/insights/river/<int:year>')
def river(year=None):
    today = date.today()
    if year is None:
        year = today.year

    available_years = _available_years(today)
    if year != today.year and year not in available_years:
        return redirect(url_for('insights.river', year=today.year))

    series = _year_series(year)
    days_in_year = _days_in_year(year)

    # Rolling average (window = 14 days, centered)
    window = 14
    by_day = {d: r for (d, r, _dt) in series}
    smoothed = []
    for d in range(1, days_in_year + 1):
        vals = [by_day[k] for k in range(max(1, d - window // 2),
                                          min(days_in_year + 1, d + window // 2 + 1))
                if k in by_day]
        if vals:
            smoothed.append((d, sum(vals) / len(vals)))

    w, h = 1200, 440
    pad_l, pad_r, pad_t, pad_b = 56, 24, 28, 44
    plot_w = w - pad_l - pad_r
    plot_h = h - pad_t - pad_b

    def x_of(day):
        return pad_l + (day - 1) / max(days_in_year - 1, 1) * plot_w

    def y_of(rating):
        return pad_t + (10 - rating) / 9 * plot_h

    raw_points = [(x_of(d), y_of(r)) for (d, r, _dt) in series]
    smooth_points = [(x_of(d), y_of(r)) for (d, r) in smoothed]

    # Month label positions
    month_starts = []
    cum = 0
    for m in range(1, 13):
        month_starts.append((x_of(cum + 1), m))
        from calendar import monthrange
        cum += monthrange(year, m)[1]

    today_x = x_of(today.timetuple().tm_yday) if today.year == year else None

    ratings = [r for (_d, r, _dt) in series]
    total = len(ratings)
    avg = round(sum(ratings) / total, 2) if total else None

    return render_template(
        'insights/insights_river.html',
        year=year, current_year=today.year,
        available_years=available_years,
        total=total, avg=avg,
        w=w, h=h, pad_l=pad_l, pad_t=pad_t, plot_w=plot_w, plot_h=plot_h,
        baseline_y=pad_t + plot_h,
        raw_points=raw_points,
        smooth_points=smooth_points,
        month_starts=month_starts,
        today_x=today_x,
    )


# ── Spiral year ──────────────────────────────────────────────

@bp.route('/insights/spiral')
@bp.route('/insights/spiral/<int:year>')
def spiral(year=None):
    today = date.today()
    if year is None:
        year = today.year

    available_years = _available_years(today)
    if year != today.year and year not in available_years:
        return redirect(url_for('insights.spiral', year=today.year))

    series = _year_series(year)
    days_in_year = _days_in_year(year)

    size = 720
    cx, cy = size / 2, size / 2
    r_min = 80
    r_max = size / 2 - 40

    # Spiral parameters: one turn per month (12 turns total)
    turns = 12

    def spiral_point(day):
        t = (day - 1) / max(days_in_year - 1, 1)  # 0..1
        angle = -math.pi / 2 + 2 * math.pi * turns * t  # start at top
        r = r_min + t * (r_max - r_min)
        return cx + r * math.cos(angle), cy + r * math.sin(angle), r, angle

    # Faint guide spiral (every ~5 days for smoothness)
    guide = []
    step = 2
    for d in range(1, days_in_year + 1, step):
        x, y, _r, _a = spiral_point(d)
        guide.append((x, y))

    # Data dots
    dots = []
    for (d, r, dt) in series:
        x, y, _r, _a = spiral_point(d)
        dots.append({
            'x': x, 'y': y,
            'rating': r,
            'radius': 4 + (r - 1) / 9 * 6,   # 4..10 px
            'opacity': 1.0 - (r - 1) / 9 * 0.75,
            'date': dt,
        })

    # Month markers: position at start of each month
    from calendar import monthrange
    month_marks = []
    cum = 0
    for m in range(1, 13):
        x, y, rr, angle = spiral_point(cum + 1)
        # Place label slightly further out on the same angle
        lx = cx + (rr + 14) * math.cos(angle)
        ly = cy + (rr + 14) * math.sin(angle)
        month_marks.append({'x': x, 'y': y, 'lx': lx, 'ly': ly, 'label': '%02d' % m})
        cum += monthrange(year, m)[1]

    today_dot = None
    if today.year == year:
        tx, ty, _r, _a = spiral_point(today.timetuple().tm_yday)
        today_dot = {'x': tx, 'y': ty}

    ratings = [r for (_d, r, _dt) in series]
    total = len(ratings)
    avg = round(sum(ratings) / total, 2) if total else None

    return render_template(
        'insights/insights_spiral.html',
        year=year, current_year=today.year,
        available_years=available_years,
        total=total, avg=avg,
        size=size, cx=cx, cy=cy,
        guide=guide,
        dots=dots,
        month_marks=month_marks,
        today_dot=today_dot,
    )


# ── Rhythm: weekday × month heatmap ──────────────────────────

@bp.route('/insights/rhythm')
@bp.route('/insights/rhythm/<int:year>')
def rhythm(year=None):
    today = date.today()
    if year is None:
        year = today.year

    available_years = _available_years(today)
    if year != today.year and year not in available_years:
        return redirect(url_for('insights.rhythm', year=today.year))

    entries = MoodEntry.query.filter(
        db.extract('year', MoodEntry.date) == year
    ).all()

    # Bucket: by_cell[weekday][month] = [ratings]
    by_cell = [[[] for _ in range(12)] for _ in range(7)]
    for e in entries:
        by_cell[e.date.weekday()][e.date.month - 1].append(e.rating)

    # Cell averages + collect valid for dynamic range
    raw = [
        [
            (sum(by_cell[w][m]) / len(by_cell[w][m])) if by_cell[w][m] else None
            for m in range(12)
        ]
        for w in range(7)
    ]
    valid_avgs = [v for row in raw for v in row if v is not None]

    if valid_avgs:
        lo_avg = min(valid_avgs)
        hi_avg = max(valid_avgs)
        pad = max(0.1, (hi_avg - lo_avg) * 0.05)
        lo_scale = lo_avg - pad
        hi_scale = hi_avg + pad
        if hi_scale - lo_scale < 0.01:
            lo_scale -= 0.5
            hi_scale += 0.5
    else:
        lo_avg = hi_avg = 0.0
        lo_scale = 0.0
        hi_scale = 1.0

    # Marginal averages — per weekday and per month
    weekday_avgs = []
    for w in range(7):
        all_r = [r for m in range(12) for r in by_cell[w][m]]
        weekday_avgs.append(round(sum(all_r) / len(all_r), 2) if all_r else None)

    month_avgs = []
    for m in range(12):
        all_r = [r for w in range(7) for r in by_cell[w][m]]
        month_avgs.append(round(sum(all_r) / len(all_r), 2) if all_r else None)

    # Layout
    cell_w = 70
    cell_h = 46
    pad_l = 54
    pad_t = 38
    pad_r = 70
    pad_b = 44
    width = pad_l + 12 * cell_w + pad_r
    height = pad_t + 7 * cell_h + pad_b

    month_names = ['01','02','03','04','05','06','07','08','09','10','11','12']
    weekday_names = ['mon','tue','wed','thu','fri','sat','sun']

    cells = []
    for w in range(7):
        for m in range(12):
            avg = raw[w][m]
            count = len(by_cell[w][m])
            if avg is not None and hi_scale > lo_scale:
                t = (avg - lo_scale) / (hi_scale - lo_scale)
                t = max(0.0, min(1.0, t))
                fill_opacity = round(1.0 - t * 0.85, 3)
            else:
                fill_opacity = None
            cells.append({
                'x': pad_l + m * cell_w,
                'y': pad_t + w * cell_h,
                'w': cell_w,
                'h': cell_h,
                'weekday': weekday_names[w],
                'month': month_names[m],
                'count': count,
                'avg': round(avg, 2) if avg is not None else None,
                'fill_opacity': fill_opacity,
                'has_data': count > 0,
                'is_weekend': w >= 5,
            })

    # Month labels (top)
    month_labels = [
        {'x': pad_l + m * cell_w + cell_w / 2, 'y': pad_t - 12, 'label': month_names[m]}
        for m in range(12)
    ]
    # Month marginal row (bottom)
    month_margin = [
        {
            'x': pad_l + m * cell_w + cell_w / 2,
            'y': pad_t + 7 * cell_h + 20,
            'label': ('%.1f' % month_avgs[m]) if month_avgs[m] is not None else '—',
        }
        for m in range(12)
    ]

    # Weekday labels (left) + weekday marginal (right)
    weekday_labels = [
        {'x': pad_l - 10, 'y': pad_t + w * cell_h + cell_h / 2, 'label': weekday_names[w]}
        for w in range(7)
    ]
    weekday_margin = [
        {
            'x': pad_l + 12 * cell_w + 14,
            'y': pad_t + w * cell_h + cell_h / 2,
            'label': ('%.1f' % weekday_avgs[w]) if weekday_avgs[w] is not None else '—',
        }
        for w in range(7)
    ]

    total = len(entries)
    overall_avg = round(sum(e.rating for e in entries) / total, 2) if total else None

    return render_template(
        'insights/insights_rhythm.html',
        year=year, current_year=today.year,
        available_years=available_years,
        width=width, height=height,
        cells=cells,
        month_labels=month_labels, month_margin=month_margin,
        weekday_labels=weekday_labels, weekday_margin=weekday_margin,
        total=total, avg=overall_avg,
        color_min=round(lo_avg, 2) if valid_avgs else None,
        color_max=round(hi_avg, 2) if valid_avgs else None,
    )


# ── Polar rose: rating distribution by weekday ───────────────

@bp.route('/insights/rose')
@bp.route('/insights/rose/<int:year>')
def rose(year=None):
    today = date.today()
    if year is None:
        year = today.year

    available_years = _available_years(today)
    if year != today.year and year not in available_years:
        return redirect(url_for('insights.rose', year=today.year))

    entries = MoodEntry.query.filter(
        db.extract('year', MoodEntry.date) == year
    ).all()

    by_weekday = [[] for _ in range(7)]
    for e in entries:
        by_weekday[e.date.weekday()].append(e.rating)

    size = 720
    cx = cy = size / 2
    inner_r = 55
    outer_r = 280
    samples = 60
    sigma_rating = 0.9
    gap_rad = math.radians(4)
    sector_width = (2 * math.pi / 7) - gap_rad
    # Monday centered at top (-π/2)
    first_alpha = -math.pi / 2 - sector_width / 2

    names = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun']

    # Precompute averages for dynamic color range (so narrow real-world spreads stay readable)
    weekday_avgs = [(sum(r) / len(r)) if r else None for r in by_weekday]
    valid_avgs = [a for a in weekday_avgs if a is not None]
    if valid_avgs:
        lo_avg = min(valid_avgs)
        hi_avg = max(valid_avgs)
        # Pad so max contrast petals don't sit at absolute extremes
        pad = max(0.1, (hi_avg - lo_avg) * 0.05)
        lo_scale = lo_avg - pad
        hi_scale = hi_avg + pad
        # If all equal, fall back to a tiny synthetic range centered on the value
        if hi_scale - lo_scale < 0.01:
            lo_scale -= 0.5
            hi_scale += 0.5
    else:
        lo_avg = hi_avg = lo_scale = hi_scale = 0.0

    petals = []

    for i, (name, ratings) in enumerate(zip(names, by_weekday)):
        count = len(ratings)
        avg = weekday_avgs[i]

        # Gaussian density over rating 1..10, evaluated at `samples` positions
        dens = [0.0] * samples
        for r in ratings:
            for k in range(samples):
                pos = 1.0 + (k / (samples - 1)) * 9
                d = (pos - r) / sigma_rating
                dens[k] += math.exp(-0.5 * d * d)
        max_d = max(dens) if dens else 0.0
        norm = [(v / max_d) if max_d > 0 else 0.0 for v in dens]

        alpha_start = first_alpha + i * (sector_width + gap_rad)

        # Outer density curve: angle sweeps across the sector, radius = inner + norm*(outer-inner)
        outer_pts = []
        for k, v in enumerate(norm):
            alpha = alpha_start + (k / (samples - 1)) * sector_width
            r = inner_r + v * (outer_r - inner_r)
            outer_pts.append((
                round(cx + r * math.cos(alpha), 2),
                round(cy + r * math.sin(alpha), 2),
            ))

        # Inner arc (reverse angular direction) to close the shape
        inner_pts = []
        for k in range(samples - 1, -1, -1):
            alpha = alpha_start + (k / (samples - 1)) * sector_width
            inner_pts.append((
                round(cx + inner_r * math.cos(alpha), 2),
                round(cy + inner_r * math.sin(alpha), 2),
            ))

        # Label position — slightly outside outer_r at sector midpoint
        mid_alpha = alpha_start + sector_width / 2
        label_r = outer_r + 24
        lx = cx + label_r * math.cos(mid_alpha)
        ly = cy + label_r * math.sin(mid_alpha)

        # Dynamic color: map this petal's avg to the range [lo_scale..hi_scale] of actual weekday averages.
        # Low end (worst weekday) → black; high end (best weekday) → light.
        if avg is not None and hi_scale > lo_scale:
            t = (avg - lo_scale) / (hi_scale - lo_scale)  # 0 = worst, 1 = best
            t = max(0.0, min(1.0, t))
            fill_opacity = round(1.0 - t * 0.85, 3)
        else:
            fill_opacity = 0.05

        petals.append({
            'name': name,
            'count': count,
            'avg': round(avg, 2) if avg is not None else None,
            'points': outer_pts + inner_pts,
            'label_x': round(lx, 2),
            'label_y': round(ly, 2),
            'fill_opacity': fill_opacity,
            'has_data': count > 0,
        })

    # Reference circles
    ref_circles = [
        {'r': inner_r},
        {'r': inner_r + 0.5 * (outer_r - inner_r)},
        {'r': outer_r},
    ]

    # Rating scale tick on the Monday sector (small "1" and "10" markers at petal edges)
    mon_start = first_alpha
    mon_end = first_alpha + sector_width
    scale_ticks = [
        {
            'x': cx + (outer_r + 10) * math.cos(mon_start),
            'y': cy + (outer_r + 10) * math.sin(mon_start),
            'label': '1',
        },
        {
            'x': cx + (outer_r + 10) * math.cos(mon_end),
            'y': cy + (outer_r + 10) * math.sin(mon_end),
            'label': '10',
        },
    ]

    total = len(entries)
    overall_avg = round(sum(e.rating for e in entries) / total, 2) if total else None

    return render_template(
        'insights/insights_rose.html',
        year=year, current_year=today.year,
        available_years=available_years,
        size=size, cx=cx, cy=cy,
        inner_r=inner_r, outer_r=outer_r,
        petals=petals,
        ref_circles=ref_circles,
        scale_ticks=scale_ticks,
        total=total, avg=overall_avg,
        color_min=round(lo_avg, 2) if valid_avgs else None,
        color_max=round(hi_avg, 2) if valid_avgs else None,
    )


# ── Ridgeline: rating distribution by month ──────────────────

@bp.route('/insights/ridgeline')
@bp.route('/insights/ridgeline/<int:year>')
def ridgeline(year=None):
    today = date.today()
    if year is None:
        year = today.year

    available_years = _available_years(today)
    if year != today.year and year not in available_years:
        return redirect(url_for('insights.ridgeline', year=today.year))

    # For each month, build a 10-bin histogram of ratings
    entries = MoodEntry.query.filter(
        db.extract('year', MoodEntry.date) == year
    ).all()
    by_month = [[] for _ in range(12)]
    for e in entries:
        by_month[e.date.month - 1].append(e.rating)

    # Sampling grid: 50 evenly-spaced x positions mapped to rating 1..10
    samples = 50
    # Upsample each 10-bin histogram into `samples` points by gaussian smoothing
    # of a finer grid (each bin becomes 5 mini-bins, rating 1..10 covers 50 positions)
    ridges = []
    month_names = ['jan','feb','mar','apr','may','jun','jul','aug','sep','oct','nov','dec']
    for m in range(12):
        ratings = by_month[m]
        count = len(ratings)
        # Build a 50-point distribution directly using gaussian kernel on each rating
        # positions[k] corresponds to rating value 1 + k*(9/49) i.e. k in 0..49 → rating 1..10
        dens = [0.0] * samples
        sigma_rating = 0.9  # in rating units
        step = 9.0 / (samples - 1)
        for r in ratings:
            for k in range(samples):
                pos = 1.0 + k * step
                d = (pos - r) / sigma_rating
                dens[k] += math.exp(-0.5 * d * d)
        # Per-month normalization so shape is comparable across sparse/dense months
        max_d = max(dens) if dens else 0.0
        norm = [(v / max_d) if max_d > 0 else 0.0 for v in dens]
        avg = round(sum(ratings) / count, 2) if count else None
        ridges.append({
            'index': m,
            'label': month_names[m],
            'count': count,
            'avg': avg,
            'values': norm,
        })

    # Layout
    w = 1040
    pad_l = 70
    pad_r = 90
    pad_t = 36
    pad_b = 44
    row_step = 38
    ridge_h = 58
    plot_w = w - pad_l - pad_r
    h = pad_t + 12 * row_step + ridge_h + pad_b

    for r in ridges:
        baseline = pad_t + r['index'] * row_step + ridge_h
        # Build SVG path: move along x, y = baseline - v*ridge_h
        pts = []
        for k, v in enumerate(r['values']):
            x = pad_l + (k / (samples - 1)) * plot_w
            y = baseline - v * ridge_h
            pts.append((round(x, 2), round(y, 2)))
        r['path_points'] = pts
        r['baseline'] = baseline
        r['x_left'] = pad_l
        r['x_right'] = pad_l + plot_w
        r['label_x'] = pad_l - 12
        r['label_y'] = baseline - 2
        r['count_x'] = pad_l + plot_w + 14
        r['count_y'] = baseline - 2

    # X-axis ticks (rating 1,3,5,7,10)
    x_ticks = []
    for r in [1, 3, 5, 7, 10]:
        x = pad_l + (r - 1) / 9 * plot_w
        x_ticks.append({'x': x, 'label': r})
    axis_y = pad_t + 12 * row_step + ridge_h + 8

    total = len(entries)
    overall_avg = round(sum(e.rating for e in entries) / total, 2) if total else None

    return render_template(
        'insights/insights_ridgeline.html',
        year=year, current_year=today.year,
        available_years=available_years,
        ridges=ridges,
        x_ticks=x_ticks,
        axis_y=axis_y,
        w=w, h=h, pad_l=pad_l,
        total=total, avg=overall_avg,
    )


# ── Words: which words correlate with good/bad days ──────────

_STOPWORDS = set("""
и в во не что он на я с со как а то все она так его но да ты к у же вы за бы
по только ее мне было вот от меня еще нет о из ему теперь когда даже ну вдруг
ли если уже или ни быть был него до вас нибудь опять уж вам ведь там потом себя
ничего ей может они тут где есть надо ней для мы тебя их чем была сам чтоб без
будто чего раз тоже себе под будет ж тогда кто этот того потому этого какой
совсем ним здесь этом один почти мой тем чтобы нее сейчас были куда зачем всех
никогда можно при наконец два об другой хоть после над больше тот через эти нас
про всего них какая много разве три эту моя впрочем хорошо свою этой перед иногда
лучше чуть том нельзя такой им более всегда конечно всю между этом этих этим
была было были быть буду будешь будет будем будете будут есть был быть будучи
день дня дни днями сегодня вчера завтра утром вечером ночью днём
the a an and or but of to in on at for with by from is are was were be been
being have has had do does did not no yes this that these those it its i you he
she we they me him her us them my your his our their as so if then than also just
very too can will would should could about into out up down over under again
still now here there when where why how what who which because while during before
after some any all each every other another own same such any of had have has
""".split())


@bp.route('/insights/words')
def words():
    """Words that correlate with good or bad days.
    For each word (≥3 occurrences), compute avg rating of days where it appears."""
    import re

    entries = MoodEntry.query.filter(MoodEntry.note.isnot(None)).all()
    entries = [e for e in entries if e.note and e.note.strip()]

    word_to_ratings = {}
    for e in entries:
        seen = set()
        for w in re.findall(r"[A-Za-zА-Яа-яЁё]{4,}", e.note.lower()):
            if w in _STOPWORDS or w in seen:
                continue
            seen.add(w)
            word_to_ratings.setdefault(w, []).append(e.rating)

    total_days = len(entries)
    global_avg = (sum(e.rating for e in entries) / total_days) if total_days else 0.0

    min_count = 3
    scored = []
    for w, ratings in word_to_ratings.items():
        if len(ratings) < min_count:
            continue
        avg = sum(ratings) / len(ratings)
        scored.append({
            'word': w,
            'count': len(ratings),
            'avg': round(avg, 2),
            'delta': round(avg - global_avg, 2),
        })

    # Top 15 lifts (highest positive delta), top 15 drags (lowest delta)
    lifts = sorted(scored, key=lambda r: (-r['delta'], -r['count']))[:15]
    drags = sorted(scored, key=lambda r: (r['delta'], -r['count']))[:15]

    # Max absolute delta for bar scaling (visual)
    max_abs = max(
        [abs(r['delta']) for r in lifts + drags] + [0.5]
    )

    return render_template(
        'insights/insights_words.html',
        lifts=lifts, drags=drags,
        total_days=total_days,
        global_avg=round(global_avg, 2),
        total_words=len(scored),
        max_abs=max_abs,
    )

