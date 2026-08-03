# index.life — Local mood diary
# https://github.com/CryptoNerf/index-life-local
# Copyright (C) 2026 Émile Alexanyan
#
# Licensed under AGPL-3.0 with additional terms per Section 7
# (preservation of author attribution, no misrepresentation of
# origin). See LICENSE and COPYRIGHT at the root of this project.
"""
Insights — landing with visualization cards + detail pages.
"""
import math
import os
import re
import json
from datetime import date, timedelta
from collections import Counter

from flask import render_template, redirect, url_for, current_app, jsonify, request

from app import db
from app.models import MoodEntry, DailySignal
from . import bp


# ── Data helpers ────────────────────────────────────────────

def _monthly_averages(year: int):
    entries = MoodEntry.query.filter(
        db.extract('year', MoodEntry.date) == year,
        MoodEntry.deleted == False,  # noqa: E712
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
        db.extract('year', MoodEntry.date) == year,
        MoodEntry.deleted == False,  # noqa: E712
    ).all()
    c = Counter(e.rating for e in entries)
    return [c.get(i, 0) for i in range(1, 11)]


def _year_heatmap(year: int, cell: int = 14, gap: int = 3):
    entries = {
        e.date: e.rating
        for e in MoodEntry.query.filter(
            db.extract('year', MoodEntry.date) == year,
            MoodEntry.deleted == False,  # noqa: E712
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
    ).filter(
        MoodEntry.deleted == False,  # noqa: E712
    ).distinct().order_by(db.text('y DESC')).all()
    years = [int(r.y) for r in rows]
    if today.year not in years:
        years.insert(0, today.year)
        years.sort(reverse=True)
    return years


# ── Routes ──────────────────────────────────────────────────

@bp.route('/graphics')
def graphics_page():
    today = date.today()
    # Mini preview for "overview" card: a tiny heatmap of current year
    preview = _year_heatmap(today.year, cell=6, gap=2)
    return render_template('graphics/graphics_landing.html',
        preview_heat=preview,
        current_year=today.year,
    )


def _nice_step(x):
    """A 'nice' axis step (1/2/5 × 10ⁿ) just above x — for clean round tick
    labels like 0.2, 0.5, 1."""
    if x <= 0:
        return 0.1
    mag = 10 ** math.floor(math.log10(x))
    for m in (1, 2, 5):
        if x <= m * mag:
            return m * mag
    return 10 * mag


def _mood_by_numeric(corr):
    """Clean 'average mood by <numeric signal>' line chart — the matplotlib
    look: a grid, a connected line through circular markers, round tick labels,
    and happy/sad face anchors on the mood axis. The signal's values are binned
    so the line stays readable. Source-agnostic: given any numeric correlation
    result (weather temperature, step count, …) it returns the pixel geometry,
    or None when there's too little data."""
    corr = corr or {}
    pts = corr.get('points') or []
    if len(pts) < 4:
        return None
    temps = [p[0] for p in pts]
    tmin, tmax = min(temps), max(temps)
    if tmax - tmin < 1.0:
        return None

    bin_w = max(1.0, round((tmax - tmin) / 18))   # aim for ≲20 readable points
    buckets: dict = {}
    for t, r in pts:
        buckets.setdefault(round((t - tmin) / bin_w), []).append(r)
    bins = sorted(({'temp': tmin + k * bin_w, 'mood': sum(v) / len(v), 'count': len(v)}
                   for k, v in buckets.items()), key=lambda b: b['temp'])
    if len(bins) < 3:
        return None

    moods = [b['mood'] for b in bins]
    step = _nice_step(max(0.5, max(moods) - min(moods)) / 8)
    ylo = math.floor(min(moods) / step) * step
    yhi = math.ceil(max(moods) / step) * step
    if yhi - ylo < step:
        yhi = ylo + step
    # An extreme value landing exactly on a round tick (mood 7.0 with a 0.5
    # step) put its marker on the frame, where the 4.5px dot and the round
    # line cap hang outside the chart. Give it another step of air.
    if max(moods) > yhi - step * 0.12:
        yhi += step
    if min(moods) < ylo + step * 0.12:
        ylo -= step
    yvals, v = [], ylo
    while v <= yhi + 1e-9:
        yvals.append(round(v, 4))
        v += step

    w, h = 900, 600
    pad_l, pad_r, pad_t, pad_b = 92, 28, 58, 66
    plot_w, plot_h = w - pad_l - pad_r, h - pad_t - pad_b

    # Same on the horizontal axis: the coldest and warmest bins would sit on
    # the left and right spines, so the domain is the bins' own extent —
    # each bin covers half a width either side of its label temperature.
    # (A bin's centre can sit up to half a width beyond the raw min/max,
    # which is why this measures the bins and not the source readings.)
    xlo = bins[0]['temp'] - bin_w / 2
    xhi = bins[-1]['temp'] + bin_w / 2

    def x_of(t):
        return pad_l + (t - xlo) / (xhi - xlo) * plot_w

    def y_of(m):
        return pad_t + (yhi - m) / (yhi - ylo) * plot_h

    points = [{'x': round(x_of(b['temp']), 1), 'y': round(y_of(b['mood']), 1),
               'temp': round(b['temp']), 'mood': round(b['mood'], 2), 'count': b['count']}
              for b in bins]
    line_d = 'M' + ' L'.join('%.1f,%.1f' % (p['x'], p['y']) for p in points)

    n = len(points)
    every = 1 if n <= 14 else (2 if n <= 26 else 3)
    xticks = [{'x': p['x'], 'label': p['temp']} for i, p in enumerate(points) if i % every == 0]
    yticks = [{'y': round(y_of(val), 1), 'label': ('%g' % round(val, 2))} for val in yvals]

    return {
        'w': w, 'h': h, 'pad_l': pad_l, 'pad_r': pad_r, 'pad_t': pad_t, 'pad_b': pad_b,
        'plot_w': plot_w, 'plot_h': plot_h,
        'baseline_y': pad_t + plot_h, 'right_x': pad_l + plot_w,
        'points': points, 'line_d': line_d, 'xticks': xticks, 'yticks': yticks,
        'face_x': round(pad_l / 2), 'face_top_y': pad_t + 2,
        'face_bot_y': pad_t + plot_h - 2,
    }


def _weather_stat_tiles(temp, precip, cond):
    """Three plain-language stat cards for the chart sidebar: how much better
    warm days are than cold ones, dry days than rainy ones, and the user's
    single best weather. Deliberately skips the Pearson coefficient — the
    warm-minus-cold gap says the same thing in plain mood points."""
    from app.i18n import t, get_current_lang
    from app import signals
    tiles = []
    if temp.get('kind') == 'numeric' and temp.get('high_avg') is not None \
            and temp.get('low_avg') is not None:
        warm, cold = temp['high_avg'], temp['low_avg']
        tiles.append({'value': '%+.1f' % round(warm - cold, 1),
                      'label': t('weather.tile_warmcold'),
                      'sub': t('weather.tile_warmcold_sub', warm=warm, cold=cold)})
    if precip.get('kind') == 'numeric' and precip.get('points'):
        wet = [m for p, m in precip['points'] if p > 1.0]
        dry = [m for p, m in precip['points'] if p <= 1.0]
        if wet and dry:
            wa, da = round(sum(wet) / len(wet), 1), round(sum(dry) / len(dry), 1)
            tiles.append({'value': '%+.1f' % round(da - wa, 1),
                          'label': t('weather.tile_wetdry'),
                          'sub': t('weather.tile_wetdry_sub', dry=da, wet=wa)})
    groups = cond.get('groups') or []   # sorted happiest → saddest upstream
    if groups:
        best = groups[0]
        tiles.append({'value': signals.condition_label(best['label'], get_current_lang()),
                      'label': t('weather.tile_best'),
                      'sub': t('weather.tile_best_sub', mood=best['avg'])})
    return tiles or None


@bp.route('/graphics/weather')
def weather():
    """Mood × weather page: a clean 'average mood by temperature' line chart
    (grid + connected markers + happy/sad face anchors) with three headline
    tiles (warm vs cold, dry vs rainy, best weather) in the sidebar."""
    from app import signals

    temp = signals.correlate_signal_with_mood('weather', 'temp_c')
    cond = signals.correlate_signal_with_mood('weather', 'condition')
    precip = signals.correlate_signal_with_mood('weather', 'precip_mm')
    has_data = temp.get('kind') != 'empty' or cond.get('kind') != 'empty'
    overall = temp.get('overall_avg')
    if overall is None:
        overall = cond.get('overall_avg')

    line_chart = _mood_by_numeric(temp) if temp.get('kind') == 'numeric' else None
    stats = _weather_stat_tiles(temp, precip, cond)

    return render_template('graphics/graphics_weather.html',
        has_data=has_data, line_chart=line_chart, stats=stats,
        overall=round(overall, 1) if overall is not None else None,
        weather_configured=bool(signals.is_weather_enabled()
                                and signals.get_weather_location()),
        current_year=date.today().year,
    )


@bp.route('/graphics/overview')
@bp.route('/graphics/overview/<int:year>')
def overview(year=None):
    today = date.today()
    if year is None:
        year = today.year

    available_years = _available_years(today)
    if year != today.year and year not in available_years:
        return redirect(url_for('graphics.overview', year=today.year))

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
        db.extract('year', MoodEntry.date) == year,
        MoodEntry.deleted == False,  # noqa: E712
    ).all()
    ratings = [e.rating for e in all_entries]
    total = len(ratings)
    avg = round(sum(ratings)/total, 2) if total else None

    return render_template('graphics/graphics_overview.html',
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
        db.extract('year', MoodEntry.date) == year,
        MoodEntry.deleted == False,  # noqa: E712
    ).order_by(MoodEntry.date.asc()).all()
    return [(e.date.timetuple().tm_yday, e.rating, e.date) for e in entries]


def _days_in_year(year: int) -> int:
    return 366 if (year % 4 == 0 and year % 100 != 0) or (year % 400 == 0) else 365


# ── River of mood ────────────────────────────────────────────

@bp.route('/graphics/river')
@bp.route('/graphics/river/<int:year>')
def river(year=None):
    today = date.today()
    if year is None:
        year = today.year

    available_years = _available_years(today)
    if year != today.year and year not in available_years:
        return redirect(url_for('graphics.river', year=today.year))

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

    return render_template('graphics/graphics_river.html',
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

@bp.route('/graphics/spiral')
@bp.route('/graphics/spiral/<int:year>')
def spiral(year=None):
    today = date.today()
    if year is None:
        year = today.year

    available_years = _available_years(today)
    if year != today.year and year not in available_years:
        return redirect(url_for('graphics.spiral', year=today.year))

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

    return render_template('graphics/graphics_spiral.html',
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

@bp.route('/graphics/rhythm')
@bp.route('/graphics/rhythm/<int:year>')
def rhythm(year=None):
    today = date.today()
    if year is None:
        year = today.year

    available_years = _available_years(today)
    if year != today.year and year not in available_years:
        return redirect(url_for('graphics.rhythm', year=today.year))

    entries = MoodEntry.query.filter(
        db.extract('year', MoodEntry.date) == year,
        MoodEntry.deleted == False,  # noqa: E712
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

    return render_template('graphics/graphics_rhythm.html',
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

@bp.route('/graphics/rose')
@bp.route('/graphics/rose/<int:year>')
def rose(year=None):
    today = date.today()
    if year is None:
        year = today.year

    available_years = _available_years(today)
    if year != today.year and year not in available_years:
        return redirect(url_for('graphics.rose', year=today.year))

    entries = MoodEntry.query.filter(
        db.extract('year', MoodEntry.date) == year,
        MoodEntry.deleted == False,  # noqa: E712
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

        mid_alpha = alpha_start + sector_width / 2
        max_half = (sector_width / 2) * 0.9

        # Symmetric petal centred on the sector midline: radius = rating level
        # (base = 1 … tip = 10), angular half-width = that rating's density, so
        # the petal bulges where ratings cluster — straight, not skewed.
        outer_pts = []
        for k, v in enumerate(norm):
            r = inner_r + (k / (samples - 1)) * (outer_r - inner_r)
            alpha = mid_alpha + v * max_half
            outer_pts.append((
                round(cx + r * math.cos(alpha), 2),
                round(cy + r * math.sin(alpha), 2),
            ))

        inner_pts = []
        for k in range(samples - 1, -1, -1):
            r = inner_r + (k / (samples - 1)) * (outer_r - inner_r)
            alpha = mid_alpha - norm[k] * max_half
            inner_pts.append((
                round(cx + r * math.cos(alpha), 2),
                round(cy + r * math.sin(alpha), 2),
            ))

        # Label position — slightly outside outer_r at sector midpoint
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

    # Rating scale marker: radius now maps to rating (1 at the base near the
    # centre, 10 at the tip). Put the two ticks along the left edge of the
    # Monday sector so they don't collide with the "пн" label at the midline.
    mon_edge = first_alpha
    scale_ticks = [
        {
            'x': cx + (inner_r - 2) * math.cos(mon_edge),
            'y': cy + (inner_r - 2) * math.sin(mon_edge),
            'label': '1',
        },
        {
            'x': cx + (outer_r + 8) * math.cos(mon_edge),
            'y': cy + (outer_r + 8) * math.sin(mon_edge),
            'label': '10',
        },
    ]

    total = len(entries)
    overall_avg = round(sum(e.rating for e in entries) / total, 2) if total else None

    return render_template('graphics/graphics_rose.html',
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

@bp.route('/graphics/ridgeline')
@bp.route('/graphics/ridgeline/<int:year>')
def ridgeline(year=None):
    today = date.today()
    if year is None:
        year = today.year

    available_years = _available_years(today)
    if year != today.year and year not in available_years:
        return redirect(url_for('graphics.ridgeline', year=today.year))

    # For each month, build a 10-bin histogram of ratings
    entries = MoodEntry.query.filter(
        db.extract('year', MoodEntry.date) == year,
        MoodEntry.deleted == False,  # noqa: E712
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

    return render_template('graphics/graphics_ridgeline.html',
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


@bp.route('/graphics/words')
def words():
    """Words that correlate with good or bad days.
    For each word (≥3 occurrences), compute avg rating of days where it appears.

    Person mentions (collected by the AI Psychologist module into the
    `EntryPerson` table) are excluded — those have their own dedicated
    People chart, and leaking names like "андрей" into Words muddied the
    answer. Filter both by direct match and by lemma so declensions
    ("Андрея", "Андрею") drop out alongside the canonical form."""
    import re

    # Build the exclusion set of lowercase person-mention base forms.
    # Gated on assistant module so users without LLM extraction still get
    # a working Words chart (just without the name filter).
    # Each stored mention is also re-normalised through _normalize_mention
    # so older rows captured before the proper-noun Name-tag lemma was in
    # place ("Димой", "Арману") collapse to their canonical form ("Дима",
    # "Арман") and the filter doesn't miss "дима" because only "димой"
    # was saved.
    person_forms: set[str] = set()
    lemmatise = None
    if 'assistant' in current_app.config.get('ACTIVE_MODULES', []):
        try:
            from app.models import EntryPerson
            from app.modules.assistant.memory import (
                _to_nominative, _normalize_mention,
            )
            lemmatise = _to_nominative
            for (mention,) in (
                db.session.query(EntryPerson.mention).distinct().all()
            ):
                if not mention:
                    continue
                person_forms.add(mention.strip().lower())
                normalised = _normalize_mention(mention)
                if normalised:
                    person_forms.add(normalised.lower())
        except Exception:
            pass

    # Per-word lemma cache so we don't re-run pymorphy3 on duplicates
    # within the same request.
    lemma_cache: dict[str, str] = {}

    def _is_person(word: str) -> bool:
        if word in person_forms:
            return True
        if lemmatise is None:
            return False
        if word not in lemma_cache:
            try:
                lemma_cache[word] = (lemmatise(word) or word).lower()
            except Exception:
                lemma_cache[word] = word
        return lemma_cache[word] in person_forms

    entries = MoodEntry.query.filter(
        MoodEntry.note.isnot(None),
        MoodEntry.deleted == False,  # noqa: E712
    ).all()
    entries = [e for e in entries if e.note and e.note.strip()]

    word_to_ratings = {}
    for e in entries:
        seen = set()
        for w in re.findall(r"[A-Za-zА-Яа-яЁё]{4,}", e.note.lower()):
            if w in _STOPWORDS or w in seen or _is_person(w):
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

    return render_template('graphics/graphics_words.html',
        lifts=lifts, drags=drags,
        total_days=total_days,
        global_avg=round(global_avg, 2),
        total_words=len(scored),
        max_abs=max_abs,
    )


@bp.route('/graphics/people')
def people():
    """People/roles mentioned in diary entries, split by LLM-extracted tone.

    Gated: requires the assistant module to be active — it holds the LLM
    that extracts per-mention sentiment via `extract_people_mentions`.
    Without it, the entry_people table can be empty or stale.
    """
    active = current_app.config.get('ACTIVE_MODULES', [])
    if 'assistant' not in active:
        return redirect(url_for('graphics.graphics_page'))

    from app.models import EntryPerson, PersonAlias

    # Join MoodEntry so mentions from soft-deleted days are excluded —
    # matches the assistant's tool_people_overview and keeps the chart in
    # sync with what the user can actually see in the diary.
    rows = db.session.query(
        EntryPerson.mention, EntryPerson.tone
    ).join(
        MoodEntry, MoodEntry.id == EntryPerson.entry_id
    ).filter(
        MoodEntry.deleted == False,  # noqa: E712
    ).all()

    # Normalize at aggregation time so existing rows merge without re-
    # extraction. Also filter pronouns the LLM mistakenly extracted as
    # people ("Она", "Это"). Falls back to capitalize-only if pymorphy3
    # isn't installed (older venvs).
    try:
        from app.modules.assistant.memory import _normalize_mention as _norm
        from app.modules.assistant.memory import _is_blacklisted
    except Exception:
        def _norm(s: str) -> str:
            s = (s or '').strip()
            return s[0].upper() + s[1:] if s else s

        def _is_blacklisted(s: str) -> bool:
            return False

    # User-curated alias map for merging LLM-produced duplicate forms.
    # Walked transitively (A→B→C) with cycle protection.
    alias_map = {a.alias: a.canonical for a in PersonAlias.query.all()}

    def resolve_alias(name: str) -> str:
        seen: set = set()
        while name in alias_map and name not in seen:
            seen.add(name)
            name = alias_map[name]
        return name

    from collections import defaultdict
    by_mention = defaultdict(lambda: {'positive': 0, 'neutral': 0, 'negative': 0})
    for mention, tone in rows:
        # Normalize first, then check against blacklist — generic roles
        # only match the blacklist after lemmatization ("друзья" → "друг").
        key = resolve_alias(_norm(mention))
        if _is_blacklisted(key):
            continue
        by_mention[key][tone] = by_mention[key].get(tone, 0) + 1

    min_count = 3
    # Bayesian-smooth the tone toward 0 (neutral) so a name with a small
    # all-positive sample doesn't outrank one with many positive mentions
    # and a few negatives. With prior=5: "Марина" (9+/0-, n=9) → 0.64;
    # "Мари" (35+/3-, n=38) → 0.74. The smoothing kicks in for small N
    # and almost disappears as the sample grows.
    PRIOR = 5
    scored = []
    for mention, counts in by_mention.items():
        total = counts['positive'] + counts['neutral'] + counts['negative']
        if total < min_count:
            continue
        tone_score = (counts['positive'] - counts['negative']) / (total + PRIOR)
        scored.append({
            'mention': mention,
            'count': total,
            'positive': counts['positive'],
            'neutral': counts['neutral'],
            'negative': counts['negative'],
            'tone': round(tone_score, 2),
        })

    lifts = sorted(
        [s for s in scored if s['tone'] > 0],
        key=lambda r: (-r['tone'], -r['count']),
    )[:15]
    drags = sorted(
        [s for s in scored if s['tone'] < 0],
        key=lambda r: (r['tone'], -r['count']),
    )[:15]

    total_mentions = sum(s['count'] for s in scored)
    max_abs = max([abs(r['tone']) for r in lifts + drags] + [0.5])

    # Backfill progress hint: if entries with notes exist but mentions are empty,
    # extraction is likely still running.
    has_notes = db.session.query(MoodEntry).filter(
        MoodEntry.note.isnot(None), MoodEntry.note != '',
        MoodEntry.deleted == False,  # noqa: E712
    ).count()

    return render_template('graphics/graphics_people.html',
        lifts=lifts, drags=drags,
        total_people=len(scored),
        total_mentions=total_mentions,
        has_notes=has_notes,
        max_abs=max_abs,
    )


@bp.route('/graphics/activities')
def activities():
    """Packed-circles chart of what the user does, sized by frequency,
    colored by the average mood on days when the activity appears.

    Gated: requires assistant module — LLM extracts canonical activity
    labels (`спорт`, `программирование`) into entry_activities via
    `extract_activities`. Without it, the table is empty.
    """
    active = current_app.config.get('ACTIVE_MODULES', [])
    if 'assistant' not in active:
        return redirect(url_for('graphics.graphics_page'))

    from app.models import EntryActivity

    # Join activities with entry ratings so we can compute per-activity mood
    rows = db.session.query(
        EntryActivity.activity, MoodEntry.rating
    ).join(
        MoodEntry, MoodEntry.id == EntryActivity.entry_id
    ).filter(
        MoodEntry.deleted == False,  # noqa: E712
    ).all()

    from collections import defaultdict
    by_activity: dict[str, list[int]] = defaultdict(list)
    for activity, rating in rows:
        by_activity[str(activity).strip().lower()].append(rating)

    # Baseline — user's overall average mood across all rated entries
    baseline = db.session.query(db.func.avg(MoodEntry.rating)).filter(
        MoodEntry.deleted == False,  # noqa: E712
    ).scalar() or 0
    baseline = float(baseline)

    min_count = 2
    items = []
    for label, ratings in by_activity.items():
        if len(ratings) < min_count or not label:
            continue
        avg = sum(ratings) / len(ratings)
        items.append({
            'label': label,
            'count': len(ratings),
            'avg': round(avg, 2),
            'delta': round(avg - baseline, 2),
        })

    # Sort by count desc for stable circle packing (larger first)
    items.sort(key=lambda r: (-r['count'], r['label']))
    items = items[:60]  # cap — past 60 circles the chart gets crowded

    has_notes = db.session.query(MoodEntry).filter(
        MoodEntry.note.isnot(None), MoodEntry.note != '',
        MoodEntry.deleted == False,  # noqa: E712
    ).count()

    total_mentions = sum(i['count'] for i in items)
    max_delta = max([abs(i['delta']) for i in items] + [0.5])

    return render_template('graphics/graphics_activities.html',
        activities=items,
        total_activities=len(items),
        total_mentions=total_mentions,
        has_notes=has_notes,
        baseline=round(baseline, 2),
        max_delta=round(max_delta, 2),
    )


@bp.route('/graphics/people/manage')
def people_manage():
    """Bulk management page — see all unique person mentions grouped by
    canonical, with checkboxes and a single merge action. Solves the
    "30 clicks for one person with 10 forms" problem of the per-detail
    merge UI.
    """
    err = _require_assistant()
    if err:
        return err

    from app.models import EntryPerson, PersonAlias

    try:
        from app.modules.assistant.memory import _normalize_mention as _norm
        from app.modules.assistant.memory import _is_blacklisted
    except Exception:
        def _norm(s: str) -> str:
            s = (s or '').strip()
            return s[0].upper() + s[1:] if s else s

        def _is_blacklisted(s: str) -> bool:
            return False

    alias_map = {a.alias: a.canonical for a in PersonAlias.query.all()}

    def resolve_alias(n: str) -> str:
        seen: set = set()
        while n in alias_map and n not in seen:
            seen.add(n)
            n = alias_map[n]
        return n

    # Per-form counts straight from entry_people, normalized so case
    # variants ("маша"/"Маша") collapse before grouping.
    raw_rows = (
        db.session.query(EntryPerson.mention, db.func.count(EntryPerson.id))
        .join(MoodEntry, MoodEntry.id == EntryPerson.entry_id)
        .filter(MoodEntry.deleted == False)  # noqa: E712
        .group_by(EntryPerson.mention)
        .all()
    )

    # Each entry: {name, count} where name = normalized mention
    by_normalized: dict[str, int] = {}
    for mention, count in raw_rows:
        norm = _norm(mention)
        if _is_blacklisted(norm):
            continue
        by_normalized[norm] = by_normalized.get(norm, 0) + int(count)

    # Group by canonical (alias resolution)
    groups: dict[str, dict] = {}
    for name, count in by_normalized.items():
        canon = resolve_alias(name)
        g = groups.setdefault(canon, {'canonical': canon, 'total': 0, 'members': []})
        g['total'] += count
        g['members'].append({'name': name, 'count': count, 'is_canonical': name == canon})

    # Sort: groups by total desc; within group, canonical first then aliases by count desc
    group_list = []
    for canon, g in groups.items():
        g['members'].sort(key=lambda m: (not m['is_canonical'], -m['count'], m['name']))
        group_list.append(g)
    group_list.sort(key=lambda g: (-g['total'], g['canonical']))

    # All canonical names — fed into the target <datalist> for autocomplete
    all_canonicals = sorted(groups.keys())

    return render_template('graphics/graphics_people_manage.html',
        groups=group_list,
        all_canonicals=all_canonicals,
        total_groups=len(group_list),
        total_unique_names=len(by_normalized),
    )


@bp.route('/graphics/people/alias/bulk', methods=['POST'])
def people_alias_bulk():
    """Merge a set of selected names into a single target canonical.

    Form fields:
      target — name to merge INTO (existing canonical OR a new typed name)
      selected — list of names being merged (passed multiple times as
                 selected=Name1, selected=Name2, ...)

    For each selected name:
      - Re-point any existing aliases that pointed to it
      - Make the name itself an alias of target
    Skips entries equal to the target (no-op self-alias).
    """
    err = _require_assistant()
    if err:
        return err

    target = (request.form.get('target') or '').strip()
    selected = [s.strip() for s in request.form.getlist('selected') if s.strip()]

    if not target or not selected:
        return redirect(url_for('graphics.people_manage'))

    from app.models import PersonAlias

    # Resolve target through existing aliases (in case user picked an
    # alias as target via autocomplete) so we always merge into a true
    # canonical, never create a chain that lands at someone else.
    aliases = {a.alias: a.canonical for a in PersonAlias.query.all()}

    def resolve(name: str) -> str:
        seen: set = set()
        while name in aliases and name not in seen:
            seen.add(name)
            name = aliases[name]
        return name

    target = resolve(target)

    for name in selected:
        if name == target:
            continue
        # If `name` was canonical for other aliases, re-point those aliases
        # so they land at the new target (preserves transitivity).
        PersonAlias.query.filter_by(canonical=name).update({'canonical': target})
        # Make `name` itself an alias of target — overwriting any existing
        # mapping it might have had to a different canonical.
        PersonAlias.query.filter_by(alias=name).delete()
        db.session.add(PersonAlias(alias=name, canonical=target))

    db.session.commit()
    return redirect(url_for('graphics.people_manage'))


@bp.route('/graphics/people/alias/create', methods=['POST'])
def people_alias_create():
    """Create an alias mapping `alias → canonical`. Used by the merge
    button on the detail page. POST form fields: alias, canonical."""
    err = _require_assistant()
    if err:
        return err

    alias = (request.form.get('alias') or '').strip()
    canonical = (request.form.get('canonical') or '').strip()
    if not alias or not canonical or alias == canonical:
        return redirect(url_for('graphics.people'))

    from app.models import PersonAlias
    # Replace existing mapping for this alias if any (idempotent updates).
    existing = PersonAlias.query.filter_by(alias=alias).first()
    if existing:
        existing.canonical = canonical
    else:
        db.session.add(PersonAlias(alias=alias, canonical=canonical))
    db.session.commit()
    return redirect(url_for('graphics.people_detail', name=canonical))


@bp.route('/graphics/people/alias/set_canonical', methods=['POST'])
def people_alias_set_canonical():
    """Promote one of the merged names to be the displayed canonical.
    All current aliases get re-pointed to the new canonical, and the
    previous canonical becomes an alias of the new one.

    POST form fields:
      new_canonical — name to display from now on (must not equal current)
      current_canonical — the displayed name on the page that's being changed
    """
    err = _require_assistant()
    if err:
        return err

    new_canonical = (request.form.get('new_canonical') or '').strip()
    current_canonical = (request.form.get('current_canonical') or '').strip()
    if not new_canonical or not current_canonical or new_canonical == current_canonical:
        return redirect(url_for('graphics.people'))

    from app.models import PersonAlias

    # 1. Remove any outgoing alias from new_canonical (it's becoming
    #    canonical itself, so it can't simultaneously be an alias).
    PersonAlias.query.filter_by(alias=new_canonical).delete()

    # 2. Re-point all aliases that resolved to current_canonical so they
    #    now resolve to new_canonical.
    PersonAlias.query.filter_by(canonical=current_canonical).update(
        {'canonical': new_canonical}
    )

    # 3. Make the previous canonical itself an alias of the new one,
    #    so any historical entry_people rows under that name keep flowing
    #    to the merged group.
    db.session.add(PersonAlias(alias=current_canonical, canonical=new_canonical))
    db.session.commit()

    return redirect(url_for('graphics.people_detail', name=new_canonical))


@bp.route('/graphics/people/alias/delete', methods=['POST'])
def people_alias_delete():
    """Remove an alias mapping. POST form field: alias."""
    err = _require_assistant()
    if err:
        return err

    alias = (request.form.get('alias') or '').strip()
    if not alias:
        return redirect(url_for('graphics.people'))

    from app.models import PersonAlias
    PersonAlias.query.filter_by(alias=alias).delete()
    db.session.commit()
    # Stay on the detail page the user came from
    came_from = (request.form.get('return_to') or '').strip()
    if came_from:
        return redirect(url_for('graphics.people_detail', name=came_from))
    return redirect(url_for('graphics.people'))


@bp.route('/graphics/activities/zoom')
def activities_zoom():
    """Zoomable circle packing of activities — top-level circles are
    activities (sized by frequency, shaded by mood), child circles are
    individual entry mentions. Click an activity to zoom into its
    mentions; hover a mention to see the note text.
    """
    err = _require_assistant()
    if err:
        return err

    from app.models import EntryActivity
    from collections import defaultdict

    rows = db.session.query(
        EntryActivity.activity, MoodEntry.date,
        MoodEntry.rating, MoodEntry.note,
    ).join(
        MoodEntry, MoodEntry.id == EntryActivity.entry_id
    ).filter(
        MoodEntry.deleted == False,  # noqa: E712
    ).all()

    by_activity = defaultdict(list)
    for activity, edate, rating, note in rows:
        label = str(activity).strip().lower()
        if not label:
            continue
        by_activity[label].append({
            'name': edate.isoformat(),
            'date': edate.isoformat(),
            'rating': rating,
            'note': note or '',
            'value': 1,
        })

    baseline_raw = db.session.query(db.func.avg(MoodEntry.rating)).filter(
        MoodEntry.deleted == False,  # noqa: E712
    ).scalar()
    baseline = float(baseline_raw) if baseline_raw is not None else 0.0

    activities_list = []
    for label, mentions in by_activity.items():
        if len(mentions) < 2:
            continue
        ratings = [m['rating'] for m in mentions]
        avg = sum(ratings) / len(ratings)
        activities_list.append({
            'name': label,
            'count': len(mentions),
            'delta': round(avg - baseline, 2),
            'avg': round(avg, 2),
            'children': mentions,
        })

    activities_list.sort(key=lambda x: -x['count'])
    activities_list = activities_list[:60]

    has_notes = db.session.query(MoodEntry).filter(
        MoodEntry.note.isnot(None), MoodEntry.note != '',
        MoodEntry.deleted == False,  # noqa: E712
    ).count()

    max_delta = max([abs(a['delta']) for a in activities_list] + [0.5])

    data = {'name': 'root', 'children': activities_list}

    return render_template('graphics/graphics_activities_zoom.html',
        data=data,
        total_activities=len(activities_list),
        baseline=round(baseline, 2),
        max_delta=round(max_delta, 2),
        has_notes=has_notes,
    )


@bp.route('/graphics/people/detail')
def people_detail():
    """Per-person detail page — every entry mentioning this person plus the
    tone the LLM assigned to each mention. Lets the user verify why a
    person ended up in the lifts or drags column."""
    err = _require_assistant()
    if err:
        return err

    name = request.args.get('name', '').strip()
    if not name:
        return redirect(url_for('graphics.people'))

    from app.models import EntryPerson

    # Match by normalized form AND walk user-defined aliases so that
    # entries originally tagged "Марь" surface on the "Мари" detail page
    # once the user has merged them.
    try:
        from app.modules.assistant.memory import _normalize_mention as _norm
        from app.modules.assistant.memory import _is_blacklisted
    except Exception:
        def _norm(s: str) -> str:
            s = (s or '').strip()
            return s[0].upper() + s[1:] if s else s

        def _is_blacklisted(s: str) -> bool:
            return False

    from app.models import PersonAlias
    alias_map = {a.alias: a.canonical for a in PersonAlias.query.all()}

    def resolve_alias(n: str) -> str:
        seen: set = set()
        while n in alias_map and n not in seen:
            seen.add(n)
            n = alias_map[n]
        return n

    # The query parameter might itself be an alias — resolve to its canonical
    target = resolve_alias(_norm(name))

    rows = db.session.query(
        EntryPerson.entry_id, EntryPerson.mention, EntryPerson.tone
    ).join(
        MoodEntry, MoodEntry.id == EntryPerson.entry_id
    ).filter(
        MoodEntry.deleted == False,  # noqa: E712
    ).all()

    by_entry: dict[int, list[str]] = {}
    for entry_id, mention, tone in rows:
        if resolve_alias(_norm(mention)) == target:
            by_entry.setdefault(entry_id, []).append(tone)

    # Aliases pointing INTO target — show on page so user can unmerge
    incoming_aliases = [
        a for a, c in alias_map.items() if resolve_alias(c) == target and a != target
    ]

    # All other canonical names from the chart, for the merge dropdown.
    # Build the same way the chart does so the user only sees relevant
    # options (already-merged variants are hidden).
    all_mentions = db.session.query(EntryPerson.mention).distinct().all()
    other_canonicals_set: set = set()
    for (m,) in all_mentions:
        c = resolve_alias(_norm(m))
        if not _is_blacklisted(c) and c != target:
            other_canonicals_set.add(c)
    other_canonicals = sorted(other_canonicals_set)

    counts = {'positive': 0, 'neutral': 0, 'negative': 0}
    if not by_entry:
        return render_template('graphics/graphics_people_detail.html',
            name=target, entries=[], counts=counts, total=0, tone_score=0.0,
        )

    entries = MoodEntry.query.filter(
        MoodEntry.id.in_(by_entry.keys())
    ).order_by(MoodEntry.date.desc()).all()

    items = []
    for e in entries:
        tones = by_entry.get(e.id, [])
        for t in tones:
            counts[t] = counts.get(t, 0) + 1
        items.append({
            'date': e.date,
            'rating': e.rating,
            'tones': tones,
            'note': e.note or '',
        })

    total = sum(counts.values())
    tone_score = (
        round((counts['positive'] - counts['negative']) / total, 2)
        if total else 0.0
    )

    return render_template('graphics/graphics_people_detail.html',
        name=target, entries=items, counts=counts, total=total,
        tone_score=tone_score,
        incoming_aliases=incoming_aliases,
        other_canonicals=other_canonicals,
    )


# ── Per-chart re-extract endpoints (LLM-only rebuild for one chart) ──────

def _require_assistant():
    if 'assistant' not in current_app.config.get('ACTIVE_MODULES', []):
        return jsonify({'error': 'Assistant module not active'}), 400
    return None


@bp.route('/graphics/people/reextract', methods=['POST'])
def people_reextract():
    err = _require_assistant()
    if err:
        return err
    from app.modules.assistant.background import reextract_people_async
    started = reextract_people_async(current_app._get_current_object())
    return jsonify({'started': started})


@bp.route('/graphics/people/reextract/status')
def people_reextract_status():
    from app.modules.assistant.background import get_people_extract_status
    return jsonify(get_people_extract_status())


@bp.route('/graphics/activities/reextract', methods=['POST'])
def activities_reextract():
    err = _require_assistant()
    if err:
        return err
    from app.modules.assistant.background import reextract_activities_async
    started = reextract_activities_async(current_app._get_current_object())
    return jsonify({'started': started})


@bp.route('/graphics/activities/reextract/status')
def activities_reextract_status():
    from app.modules.assistant.background import get_activities_extract_status
    return jsonify(get_activities_extract_status())


@bp.route('/graphics/people/update', methods=['POST'])
def people_update():
    """Incremental "update AI data" for the People chart: extract names for
    entries missing them only (preserves existing data). Shares the extract
    status with re-extract, so /graphics/people/reextract/status tracks both."""
    err = _require_assistant()
    if err:
        return err
    from app.modules.assistant.background import backfill_people_async
    started = backfill_people_async(current_app._get_current_object())
    return jsonify({'started': started})


@bp.route('/graphics/activities/update', methods=['POST'])
def activities_update():
    """Incremental "update AI data" for the Activities chart (missing entries only)."""
    err = _require_assistant()
    if err:
        return err
    from app.modules.assistant.background import backfill_activities_async
    started = backfill_activities_async(current_app._get_current_object())
    return jsonify({'started': started})


# ── "My people" — AI-free browse-entries-by-person ───────────────────
# No AI, no tone. The user adds a name; pymorphy3 matches every declined form
# across their notes; each person is a face in the "crowd", click → entries.

def _people_photo_dir():
    from pathlib import Path
    d = Path(current_app.config['UPLOAD_FOLDER']) / 'people'
    d.mkdir(parents=True, exist_ok=True)
    return d


def _entries_with_notes():
    return (MoodEntry.query
            .filter(MoodEntry.deleted == False,           # noqa: E712
                    MoodEntry.note.isnot(None), MoodEntry.note != '')
            .order_by(MoodEntry.date.desc(), MoodEntry.id.desc())
            .all())


def _silhouette_files():
    from pathlib import Path
    d = Path(__file__).parent / 'static' / 'silhouettes'
    if not d.is_dir():
        return []
    exts = ('.png', '.svg', '.webp', '.jpg', '.jpeg', '.gif')
    return sorted((f for f in d.iterdir() if f.suffix.lower() in exts),
                  key=lambda p: p.name)


def _svg_aspect(path):
    """width/height of an SVG from its viewBox (or width/height attrs). Used to
    size each silhouette by its own shape: tall ones fill the height, wide/square
    ones (sitting, dancing) get more width instead of shrinking. 1.0 on failure."""
    try:
        head = path.read_text(encoding='utf-8', errors='ignore')[:2000]
        m = re.search(r'viewBox\s*=\s*"\s*[\d.eE+-]+\s+[\d.eE+-]+\s+'
                      r'([\d.eE+-]+)\s+([\d.eE+-]+)', head)
        if m:
            w, h = float(m.group(1)), float(m.group(2))
        else:
            mw = re.search(r'\bwidth\s*=\s*"([\d.]+)', head)
            mh = re.search(r'\bheight\s*=\s*"([\d.]+)', head)
            w = float(mw.group(1)) if mw else 1.0
            h = float(mh.group(1)) if mh else 1.0
        return round(w / h, 3) if h else 1.0
    except Exception:
        return 1.0


def _silhouettes():
    """[{name, aspect}] for the picker; aspect lets templates size each one."""
    out = []
    for f in _silhouette_files():
        aspect = _svg_aspect(f) if f.suffix.lower() == '.svg' else 1.0
        out.append({'name': f.name, 'aspect': aspect})
    return out


def _silhouette_names():
    return [f.name for f in _silhouette_files()]


def _drop_photo(person):
    if person.photo_filename:
        try:
            (_people_photo_dir() / person.photo_filename).unlink(missing_ok=True)
        except Exception:
            pass
        person.photo_filename = None


def _apply_avatar(person):
    """Set the person's avatar from the form: an uploaded photo wins; otherwise a
    picked silhouette from the library; otherwise leave the current one."""
    from werkzeug.utils import secure_filename
    file = request.files.get('photo')
    if file and file.filename:
        ext = os.path.splitext(secure_filename(file.filename))[1].lower()
        if ext in ('.jpg', '.jpeg', '.png', '.gif', '.webp'):
            fname = f'person_{person.id}{ext}'
            if person.photo_filename and person.photo_filename != fname:
                _drop_photo(person)
            file.save(str(_people_photo_dir() / fname))
            person.photo_filename = fname
            person.silhouette = None
            return
    sil = (request.form.get('silhouette') or '').strip()
    if sil == '__none__':
        person.silhouette = None
    elif sil and sil in _silhouette_names():
        person.silhouette = sil
        _drop_photo(person)


def _parse_terms(field):
    """Split a comma/newline list into a JSON array (or None if empty)."""
    parts = [p.strip() for p in re.split(r'[,\n]', request.form.get(field, '')) if p.strip()]
    return json.dumps(parts, ensure_ascii=False) if parts else None


@bp.route('/graphics/my-people')
def my_people():
    from app.models import UserPerson
    from app.people_match import mention_count
    people = UserPerson.query.all()
    entries = _entries_with_notes()
    items = [{'p': p, 'count': mention_count(p, entries)} for p in people]
    items.sort(key=lambda x: (-x['count'], x['p'].name.lower()))
    sils = _silhouettes()
    return render_template('graphics/graphics_my_people.html',
                           items=items, silhouettes=sils,
                           sil_aspect={s['name']: s['aspect'] for s in sils})


@bp.route('/graphics/my-people/add', methods=['POST'])
def my_people_add():
    from app.models import UserPerson
    name = (request.form.get('name') or '').strip()
    if not name:
        return redirect(url_for('graphics.my_people'))
    person = UserPerson(name=name)
    db.session.add(person)
    db.session.flush()  # assign id for the photo filename
    _apply_avatar(person)
    db.session.commit()
    return redirect(url_for('graphics.my_people_detail', person_id=person.id))


@bp.route('/graphics/my-people/<int:person_id>')
def my_people_detail(person_id):
    from app.models import UserPerson
    from app.people_match import matching_entry_ids, name_forms
    person = db.session.get(UserPerson, person_id)
    if person is None:
        return redirect(url_for('graphics.my_people'))
    entries = _entries_with_notes()
    ids = set(matching_entry_ids(person, entries))
    matched = [e for e in entries if e.id in ids]
    return render_template('graphics/graphics_my_people_detail.html',
        person=person, entries=matched,
        aliases=json.loads(person.aliases) if person.aliases else [],
        excluded=json.loads(person.excluded) if person.excluded else [],
        forms=name_forms(person.name), silhouettes=_silhouettes())


@bp.route('/graphics/my-people/<int:person_id>/edit', methods=['POST'])
def my_people_edit(person_id):
    from app.models import UserPerson
    person = db.session.get(UserPerson, person_id)
    if person is None:
        return redirect(url_for('graphics.my_people'))
    name = (request.form.get('name') or '').strip()
    if name:
        person.name = name
    person.aliases = _parse_terms('aliases')
    person.excluded = _parse_terms('excluded')
    _apply_avatar(person)
    db.session.commit()
    return redirect(url_for('graphics.my_people_detail', person_id=person.id))


@bp.route('/graphics/my-people/<int:person_id>/delete', methods=['POST'])
def my_people_delete(person_id):
    from app.models import UserPerson
    person = db.session.get(UserPerson, person_id)
    if person is not None:
        if person.photo_filename:
            try:
                (_people_photo_dir() / person.photo_filename).unlink(missing_ok=True)
            except Exception:
                pass
        db.session.delete(person)
        db.session.commit()
    return redirect(url_for('graphics.my_people'))


@bp.route('/graphics/my-people/photo/<path:filename>')
def my_people_photo(filename):
    from flask import send_from_directory
    return send_from_directory(str(_people_photo_dir()), filename)


@bp.route('/graphics/my-people/suggest')
def my_people_suggest():
    """Candidate names found in the notes, for the "add person" autocomplete."""
    from app.people_match import suggest_names
    return jsonify(suggest_names(_entries_with_notes()))

