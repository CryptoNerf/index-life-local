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

with application.app_context():
    # A year holding both ends of the scale, so both colours must appear.
    day = date(YEAR, 1, 6)
    for i, rating in enumerate([1, 10] * 6):
        db.session.add(MoodEntry(date=day + timedelta(days=i * 9),
                                 rating=rating, note='x'))
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
    html = body(path)
    assert LOW in html, name + ' missing the low end of the grid scale'
    assert HIGH in html, name + ' missing the high end of the grid scale'

# The rose and the rhythm grid stop advertising a range they no longer use.
for path in ('/graphics/rose', '/graphics/rhythm'):
    assert 'legend-dot' in body(path), 'legend vanished on ' + path

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
