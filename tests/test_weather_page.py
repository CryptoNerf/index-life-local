"""The weather page has to show what a number is made of.

The page named a single "best weather" from whichever condition had the
highest average, with nothing about how many days that was. On a real diary
that put four thunderstorms above eighty-six rainy days and a hundred and
seventy-two cloudy ones, across a total spread of a quarter of a point. The
arithmetic was right and the headline was not.

So: a table of every condition with its day count and its gap from the
overall average, and a minimum sample before any weather is called best.

The page tests run in a subprocess against the real app factory, like the
people-page test next door — the bare `app` fixture has no i18n and none of
the blueprints the shared header links to. The fill's progress reporting is
plain functions and is tested directly.
"""
import subprocess
import sys
from pathlib import Path

import pytest

from app import signals
from app.models import MoodEntry
from app import db


# ── the page, rendered for real ───────────────────────────────

_SCRIPT = r'''
import os, sys, tempfile
from datetime import date, timedelta
from pathlib import Path

tmp = Path(tempfile.mkdtemp())
(tmp / 'graphics_enabled').write_text('1')
os.environ['SECRET_KEY'] = 'test'
import paths
paths.user_data_dir = lambda: tmp

from app import create_app, db
application = create_app()
assert 'graphics' in application.config.get('ACTIVE_MODULES', []), 'graphics inactive'

from app.models import MoodEntry, DailySignal, UserProfile
from app.modules.graphics.routes import MIN_DAYS_FOR_BEST_WEATHER as MIN

# Condition names are translated for display, so pin the language: the seeded
# 'Thunderstorm' must be the string the page prints, or the assertions below
# would be looking for a word that never appears.
with application.app_context():
    profile = UserProfile.query.first()
    if profile is None:
        profile = UserProfile(name='', birthdate=None, email='')
        db.session.add(profile)
    profile.language = 'en'
    db.session.commit()

def seed(plan):
    with application.app_context():
        MoodEntry.query.delete()
        DailySignal.query.delete()
        db.session.commit()
        n = 0
        for condition, ratings in plan.items():
            for rating in ratings:
                d = date(2026, 1, 1) + timedelta(days=n)
                db.session.add(MoodEntry(date=d, rating=rating, note='x'))
                db.session.add(DailySignal(date=d, source='weather',
                                           metric='condition', value_text=condition))
                # Temperature too: the stat tiles — including the "best
                # weather" one under test — only render alongside the
                # temperature chart. Seeding conditions alone left no tile on
                # the page at all, and the assertions about what it must not
                # say were reading an empty string.
                db.session.add(DailySignal(date=d, source='weather',
                                           metric='temp_c',
                                           value_num=float(5 + (n % 20))))
                n += 1
        db.session.commit()

client = application.test_client()

def page():
    r = client.get('/graphics/weather')
    assert r.status_code == 200, '/graphics/weather -> %d' % r.status_code
    return r.data.decode()

TABLE_MARK = '<table class="wx-table">'

def split(html):
    """Everything before the table, and the table itself.

    Split on the markup, not on the block's class name: the class also
    appears in the page's <style>, so splitting there put the stat tiles on
    the table's side of the line and the "is it named best" assertions below
    were checking an empty string.
    """
    assert TABLE_MARK in html, 'the mood-by-weather table is missing'
    head, table = html.split(TABLE_MARK, 1)
    return head, table

# ── the real complaint: four thunderstorms on top ─────────────
seed({'Thunderstorm': [6, 6, 6, 6],
      'Rain':   [6] * 40 + [5] * 46,
      'Clouds': [6] * 80 + [5] * 92})
head, table = split(page())
assert 'wx-stat' in head, 'the stat tiles did not render — the check below is empty'
assert 'Thunderstorm' not in head, \
    'a four-day sample was still named the best weather'
assert 'Thunderstorm' in table, 'the thin group vanished instead of being shown'
assert 'wx-thin' in table, 'the thin group was shown without a caveat'
for days in ('4', '86', '172'):
    assert '>%s<' % days in table, 'day count %s missing' % days

# ── the best weather now says what it rests on ────────────────
seed({'Rain': [8] * 30, 'Clouds': [5] * 30})
head, table = split(page())
assert '30' in head, 'the tile gave an average with no sample size'

# ── nothing qualifies → nothing is named ──────────────────────
seed({'Rain': [8] * (MIN - 1), 'Clouds': [5] * (MIN - 1)})
head, table = split(page())
assert 'Rain' not in head and 'Clouds' not in head, \
    'a weather under the minimum was still named best'

# ── the table is ordered best first ───────────────────────────
seed({'Rain': [4] * 25, 'Clear': [9] * 25, 'Snow': [6] * 25})
head, table = split(page())
pos = [table.index(w) for w in ('Clear', 'Snow', 'Rain')]
assert pos == sorted(pos), 'the table was not ordered happiest first'

# ── the gap from the overall average ──────────────────────────
seed({'Clear': [7] * 25, 'Rain': [5] * 25})
head, table = split(page())
assert '+1.00' in table and '-1.00' in table, 'the difference column is wrong'

# ── a diary with no weather at all still renders ──────────────
with application.app_context():
    MoodEntry.query.delete()
    DailySignal.query.delete()
    db.session.add(MoodEntry(date=date(2026, 1, 1), rating=7, note='x'))
    db.session.commit()
html = client.get('/graphics/weather').data.decode()
assert TABLE_MARK not in html, 'an empty table was rendered anyway'

# ── the fill reports its state over HTTP ──────────────────────
body = client.get('/account/weather/backfill/status').get_json()
assert body['running'] is False and body['done_days'] == 0, body

print('WEATHER_PAGE_OK')
'''


def test_the_weather_page_shows_day_counts_and_a_qualified_best():
    result = subprocess.run(
        [sys.executable, '-c', _SCRIPT],
        cwd=Path(__file__).resolve().parent.parent,
        capture_output=True, text=True, timeout=300,
    )
    assert result.returncode == 0, f'stderr:\n{result.stderr[-3000:]}'
    assert 'WEATHER_PAGE_OK' in result.stdout


# ── the history fill's progress ───────────────────────────────

def test_progress_is_reported_in_days_as_chunks_land(app, monkeypatch):
    """A two-year fill is a dozen round trips; the page can only show
    movement if each one reports."""
    seen = []
    monkeypatch.setattr(signals, 'record_weather', lambda lat, lon, s, e: 3)

    from datetime import date
    total = signals.backfill_weather(
        0.0, 0.0, date(2024, 1, 1), date(2026, 1, 1),
        on_progress=lambda days, rows: seen.append(days))

    assert total > 0
    assert len(seen) >= 2, 'progress was reported once, at the end'
    assert seen == sorted(seen), 'days covered went backwards'
    assert seen[-1] >= 731, 'the fill claimed fewer days than it covered'


def test_progress_reporting_never_breaks_the_fill(app, monkeypatch):
    monkeypatch.setattr(signals, 'record_weather', lambda lat, lon, s, e: 1)

    from datetime import date
    total = signals.backfill_weather(
        0.0, 0.0, date(2025, 1, 1), date(2026, 1, 1),
        on_progress=lambda *a: 1 / 0)

    assert total > 0, 'a broken progress callback lost the whole fill'


def test_a_failing_fill_is_not_left_marked_running(app, monkeypatch):
    """Otherwise the page polls a spinner that never resolves."""
    def boom(*a, **kw):
        raise RuntimeError('open-meteo is down')
    monkeypatch.setattr(signals, 'record_weather', boom)
    monkeypatch.setattr(signals, 'is_weather_enabled', lambda: True)
    monkeypatch.setattr(signals, 'get_weather_location',
                        lambda: {'lat': 0.0, 'lon': 0.0, 'label': 'x'})
    from datetime import date
    db.session.add(MoodEntry(date=date(2026, 1, 1), rating=7, note='x'))
    db.session.commit()

    signals.backfill_all_weather_async(app)

    import time
    for _ in range(80):
        # Wait for `finished`, not for `running` to go false — it is false
        # for the instant before the thread starts, and the first version of
        # this test sailed straight through that window and proved nothing.
        if signals.get_backfill_status()['finished']:
            break
        time.sleep(0.05)

    status = signals.get_backfill_status()
    assert status['finished'] is True, 'the fill never reported finishing'
    assert status['running'] is False, 'a failed fill was left marked running'
    assert status['error'], 'the failure was swallowed silently'


def test_a_second_request_does_not_start_a_parallel_fill(app, monkeypatch):
    """Two overlapping fills would double every request to open-meteo."""
    import threading
    started = threading.Event()
    release = threading.Event()
    calls = []

    def slow(lat, lon, s, e, on_progress=None):
        # Patched at the fill level, not the request level: one fill makes
        # several requests (the archive chunks plus the recent window), so
        # counting requests would have called a single fill a double one.
        calls.append(1)
        started.set()
        release.wait(5)
        return 1

    monkeypatch.setattr(signals, 'backfill_weather', slow)
    monkeypatch.setattr(signals, 'is_weather_enabled', lambda: True)
    monkeypatch.setattr(signals, 'get_weather_location',
                        lambda: {'lat': 0.0, 'lon': 0.0, 'label': 'x'})
    from datetime import date
    db.session.add(MoodEntry(date=date(2026, 1, 1), rating=7, note='x'))
    db.session.commit()

    signals.backfill_all_weather_async(app)
    assert started.wait(5)
    signals.backfill_all_weather_async(app)      # the impatient second click
    import time
    time.sleep(0.2)
    release.set()

    for _ in range(80):
        if signals.get_backfill_status()['finished']:
            break
        time.sleep(0.05)
    assert len(calls) == 1, 'the second click started its own fill'


def test_a_finished_fill_does_not_make_the_page_reload_for_ever(app, monkeypatch):
    """The page reloads when a fill completes, and it decides that by
    comparing a counter against the value it was rendered with. A sticky
    "finished" boolean cannot serve: it stays true for the life of the
    process, so every later visit would see it, reload, see it again, and
    never stop."""
    monkeypatch.setattr(signals, 'record_weather', lambda lat, lon, s, e: 1)
    monkeypatch.setattr(signals, 'is_weather_enabled', lambda: True)
    monkeypatch.setattr(signals, 'get_weather_location',
                        lambda: {'lat': 0.0, 'lon': 0.0, 'label': 'x'})
    from datetime import date
    db.session.add(MoodEntry(date=date(2026, 1, 1), rating=7, note='x'))
    db.session.commit()

    def wait_for(target):
        # Wait on the counter, not on `running`: that is false for the
        # instant before the thread starts, and polling it returns at once
        # having observed nothing.
        import time
        for _ in range(100):
            if signals.get_backfill_status()['runs'] >= target:
                return
            time.sleep(0.05)

    before = signals.get_backfill_status()['runs']
    signals.backfill_all_weather_async(app)
    wait_for(before + 1)
    after_first = signals.get_backfill_status()

    assert after_first['runs'] == before + 1, 'a completed fill did not count'

    # A page rendered now carries `runs` as its baseline. Nothing further
    # happens, so the counter must not move and the page must not reload.
    baseline = after_first['runs']
    assert signals.get_backfill_status()['runs'] == baseline

    signals.backfill_all_weather_async(app)
    wait_for(baseline + 1)

    assert signals.get_backfill_status()['runs'] == baseline + 1, (
        'the next fill has to be distinguishable from the last one')
