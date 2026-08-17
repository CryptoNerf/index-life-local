"""The rating colours reach the real chart pages, not just the helper.

The precedence lives in `rating_scale`, but whether a template actually asks
for it — and whether the colour survives the CSS that paints those marks —
can only be seen by rendering the pages. Both modules have to be active, so
this runs in a subprocess against the real app factory, like the people-page
test next door.
"""
import subprocess
import sys
from pathlib import Path

_SCRIPT = r'''
import json, os, sys, tempfile
from datetime import date, timedelta
from pathlib import Path

tmp = Path(tempfile.mkdtemp())
(tmp / 'graphics_enabled').write_text('1')
(tmp / 'customization_enabled').write_text('1')
os.environ['SECRET_KEY'] = 'test'
import paths
paths.user_data_dir = lambda: tmp

from app import create_app, db
application = create_app()
for mod in ('graphics', 'customization'):
    assert mod in application.config.get('ACTIVE_MODULES', []), mod + ' inactive'

from app.models import MoodEntry, UserCustomization

YEAR = 2026
# Rating 1 and rating 10. Matched as the inline fill the templates write,
# not as bare colours: the same two values also appear on every page inside
# the grid's own `.cube.filled.rN` rules, so a bare match would pass even if
# the charts ignored the scale completely.
LOW = 'fill: rgb(192, 57, 43)'
HIGH = 'fill: rgb(42, 143, 42)'

# A rating per weekday: the year then holds both ends of the scale (so the
# charts that paint days must show both), and all seven weekday averages
# differ (so the rose, which spreads the palette over its own span, must come
# out in seven colours rather than one).
BY_WEEKDAY = [1, 3, 4, 6, 7, 9, 10]     # Monday … Sunday

with application.app_context():
    day = date(YEAR, 1, 1)
    for i in range(120):
        d = day + timedelta(days=i)
        db.session.add(MoodEntry(date=d, rating=BY_WEEKDAY[d.weekday()], note='x'))
    db.session.commit()

def settings(**values):
    with application.app_context():
        row = UserCustomization.query.first() or UserCustomization(settings_json='{}')
        row.settings_json = json.dumps(values)
        db.session.add(row)
        db.session.commit()

client = application.test_client()
PAGES = {
    'overview': '/graphics/overview',
    'spiral':   '/graphics/spiral',
    'rose':     '/graphics/rose',
    'rhythm':   '/graphics/rhythm',
    'river':    '/graphics/river',
}
# What each chart looks like when it is *not* following the grid. Four of
# them carry the rating as an inline fill-opacity; the river's daily dots
# take their transparency from CSS and only need to still be dots.
PLAIN = dict.fromkeys(PAGES, 'fill-opacity=')
PLAIN['river'] = 'river-raw-dot'

def scale_palette():
    """Every colour the grid's scale can produce, at fine resolution — a
    petal must be one of them, wherever on the span it landed."""
    from app.modules.customization import rating_scale as rs
    stops = rs.stops({})
    return {'rgb(%d, %d, %d)' % rs.rgb_at(stops, 1 + i * 9 / 900)
            for i in range(901)}


_PALETTE = None


def palette_position(color):
    """Where a colour sits on the grid's ramp, 0 (rating 1) to 1 (rating 10)."""
    global _PALETTE
    from app.modules.customization import rating_scale as rs
    if _PALETTE is None:
        stops = rs.stops({})
        _PALETTE = {'rgb(%d, %d, %d)' % rs.rgb_at(stops, 1 + i * 9 / 900): i / 900
                    for i in range(901)}
    assert color in _PALETTE, color + ' is not on the grid palette'
    return _PALETTE[color]


def body(path):
    r = client.get(path + '?year=%d' % YEAR)
    assert r.status_code == 200, path + ' -> %d' % r.status_code
    return r.data.decode()

# ── grid not coloured by rating: charts unchanged ──────────────
settings()
for name, path in PAGES.items():
    html = body(path)
    assert LOW not in html and HIGH not in html, (
        name + ' painted rating colours while the grid was plain')
    assert PLAIN[name] in html, name + ' lost its own rendering'

# ── grid coloured by rating: charts follow ────────────────────
settings(**{'cube-scale-enabled': 'true'})
for name, path in PAGES.items():
    if name == 'rose':
        continue          # spread over its own span — checked below
    html = body(path)
    assert LOW in html, name + ' missing the low end of the grid scale'
    assert HIGH in html, name + ' missing the high end of the grid scale'

# The rose compares weekdays with each other, so the palette is spread over
# the span the seven averages cover (padded, so the ends of the scale are
# deliberately never reached). What has to hold is that the petals differ.
def rose_fills():
    import re
    return set(re.findall(r'fill: (rgb\(\d+, \d+, \d+\))', body(PAGES['rose'])))

fills = rose_fills()
assert len(fills) == 7, 'the rose came out in %d colour(s), not seven' % len(fills)
assert fills <= scale_palette(), 'the rose used colours outside the grid palette'

# The case the spread exists for: seven weekday averages within about half a
# point of each other, which is what real diaries look like. Read off the
# absolute 1–10 scale they would all be the same yellow; spread over their own
# span they must still cover most of the palette.
with application.app_context():
    MoodEntry.query.delete()
    day = date(YEAR, 1, 1)
    for i in range(140):
        d = day + timedelta(days=i)
        # Every weekday averages near 5.5, drifting by a tenth per weekday.
        pattern = [1, 10, 4, 5, 6, 5, 5]
        rating = pattern[i // 7 % 7]
        if i // 7 % 7 == 6:
            rating = max(1, min(10, 5 + d.weekday() - 3))
        db.session.add(MoodEntry(date=d, rating=rating, note='x'))
    db.session.commit()

positions = sorted(palette_position(c) for c in rose_fills())
spread = positions[-1] - positions[0]
assert spread > 0.5, (
    'the rose only covered %.2f of the palette — the averages were read off '
    'the absolute scale instead of their own span' % spread)

for path in ('/graphics/rose', '/graphics/rhythm'):
    assert 'legend-dot' in body(path), 'legend vanished on ' + path

# ── the overview's bars, a surface of their own ───────────────
def bar_fills():
    import re
    return set(re.findall(r'class="bar" style="fill: (rgb\(\d+, \d+, \d+\))',
                          body(PAGES['overview'])))

bars = bar_fills()
assert len(bars) >= 3, 'the overview bars came out in %d colour(s)' % len(bars)
assert bars <= scale_palette(), 'the bars used colours outside the grid palette'

# Two surfaces, two keys: customizing one must not decide for the other.
settings(**{'cube-scale-enabled': 'true', 'overview-bar-color': '#123456'})
assert not bar_fills(), 'the bars ignored the colour the user chose for them'
assert LOW in body(PAGES['overview']), 'recolouring the bars silenced the heatmap'

settings(**{'cube-scale-enabled': 'true', 'overview-heat-color': '#123456'})
assert bar_fills(), 'recolouring the heatmap silenced the bars'

settings(**{'cube-scale-enabled': 'true'})

# ── a chart given its own colour keeps it ─────────────────────
settings(**{'cube-scale-enabled': 'true', 'spiral-dot-color': '#123456'})
spiral = body(PAGES['spiral'])
assert LOW not in spiral and HIGH not in spiral, (
    'the spiral ignored the colour the user chose for it')
assert PLAIN['spiral'] in spiral, 'the spiral lost its own rendering'
overview = body(PAGES['overview'])
assert LOW in overview, 'customizing the spiral silenced the overview too'

# ── the global chart colour outranks the grid everywhere ──────
settings(**{'cube-scale-enabled': 'true', 'chart-color': '#0000ff'})
for name, path in PAGES.items():
    html = body(path)
    assert LOW not in html and HIGH not in html, (
        name + ' ignored the global chart colour')

# ── own stops are honoured, not just the defaults ─────────────
settings(**{'cube-scale-enabled': 'true', 'cube-scale-low': '#ff00ff'})
assert 'fill: rgb(255, 0, 255)' in body(PAGES['overview']), 'custom low stop ignored'

print('CHART_GRID_COLORS_OK')
'''


def test_chart_pages_follow_the_grid_unless_customized():
    result = subprocess.run(
        [sys.executable, '-c', _SCRIPT],
        cwd=Path(__file__).resolve().parent.parent,
        capture_output=True, text=True, timeout=300,
    )
    assert result.returncode == 0, f'stderr:\n{result.stderr[-3000:]}'
    assert 'CHART_GRID_COLORS_OK' in result.stdout
