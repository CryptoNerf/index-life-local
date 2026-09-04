"""Tests for the external-signals layer (app.signals): weather provider,
upsert, mood correlation, geocoding and config — all without network
(the single HTTP entry point is stubbed)."""
from datetime import date

from app import db
from app.models import MoodEntry, DailySignal
from app import signals


# ── WMO condition mapping ─────────────────────────────────────

def test_wmo_condition_mapping():
    assert signals._wmo_condition(0) == 'Clear'
    assert signals._wmo_condition(3) == 'Clouds'
    assert signals._wmo_condition(48) == 'Fog'
    assert signals._wmo_condition(65) == 'Rain'
    assert signals._wmo_condition(75) == 'Snow'
    assert signals._wmo_condition(95) == 'Thunderstorm'
    assert signals._wmo_condition(None) is None
    assert signals._wmo_condition('not-a-code') is None


# ── Weather fetch + record (HTTP stubbed) ─────────────────────

def test_fetch_weather_parses_open_meteo(monkeypatch):
    canned = {'daily': {
        'time': ['2026-06-15', '2026-06-16'],
        'temperature_2m_mean': [18.2, 22.0],
        'precipitation_sum': [0.0, 3.5],
        'weather_code': [3, 61],
    }}
    monkeypatch.setattr(signals, '_http_get_json', lambda url: canned)

    out = signals.fetch_weather(52.5, 13.4, date(2026, 6, 15), date(2026, 6, 16))
    assert out[date(2026, 6, 15)]['temp_c'] == 18.2
    assert out[date(2026, 6, 15)]['condition'] == 'Clouds'
    assert out[date(2026, 6, 16)]['condition'] == 'Rain'
    assert out[date(2026, 6, 16)]['precip_mm'] == 3.5


def test_fetch_weather_empty_on_http_failure(monkeypatch):
    monkeypatch.setattr(signals, '_http_get_json', lambda url: None)
    assert signals.fetch_weather(0, 0, date(2026, 6, 15), date(2026, 6, 15)) == {}


def test_record_weather_upserts_and_is_idempotent(app, monkeypatch):
    canned = {'daily': {
        'time': ['2026-06-15'],
        'temperature_2m_mean': [18.0],
        'precipitation_sum': [2.0],
        'weather_code': [61],
    }}
    monkeypatch.setattr(signals, '_http_get_json', lambda url: canned)

    n = signals.record_weather(52.5, 13.4, date(2026, 6, 15), date(2026, 6, 15))
    assert n == 3  # temp_c, precip_mm, condition
    row = DailySignal.query.filter_by(
        date=date(2026, 6, 15), source='weather', metric='temp_c').first()
    assert row.value_num == 18.0
    assert DailySignal.query.filter_by(
        date=date(2026, 6, 15), source='weather', metric='condition').first().value_text == 'Rain'

    # Re-recording the same day updates in place — no duplicate rows.
    signals.record_weather(52.5, 13.4, date(2026, 6, 15), date(2026, 6, 15))
    assert DailySignal.query.filter_by(date=date(2026, 6, 15), source='weather').count() == 3


def test_backfill_weather_covers_full_range_contiguously(monkeypatch):
    from datetime import timedelta
    calls = []

    def fake_record(lat, lon, start, end):
        calls.append((start, end))
        return 1

    monkeypatch.setattr(signals, 'record_weather', fake_record)

    today = date.today()
    start = today - timedelta(days=400)          # spans archive + forecast windows
    signals.backfill_weather(10.0, 20.0, start, today)

    segs = sorted(calls)
    assert segs, 'backfill made no fetches'
    # Together the segments must cover exactly [start, today], with no gaps or
    # overlaps (each segment begins the day after the previous one ends).
    assert segs[0][0] == start
    assert segs[-1][1] == today
    for prev, nxt in zip(segs, segs[1:]):
        assert nxt[0] == prev[1] + timedelta(days=1)


def test_backfill_weather_single_recent_call(monkeypatch):
    from datetime import timedelta
    calls = []
    monkeypatch.setattr(signals, 'record_weather',
                        lambda lat, lon, s, e: calls.append((s, e)) or 1)
    today = date.today()
    # A short recent range stays one forecast-window call (no archive chunk).
    signals.backfill_weather(10.0, 20.0, today - timedelta(days=20), today)
    assert calls == [(today - timedelta(days=20), today)]


# ── Correlation ───────────────────────────────────────────────

def _add(day, rating, deleted=False):
    db.session.add(MoodEntry(date=day, rating=rating, note='x', deleted=deleted))


def test_correlate_numeric_temperature(app):
    # Mood rises perfectly with temperature → Pearson 1.0.
    rows = [(date(2026, 6, 1), 3, 5.0), (date(2026, 6, 2), 5, 10.0),
            (date(2026, 6, 3), 7, 15.0), (date(2026, 6, 4), 9, 20.0)]
    for d, rating, temp in rows:
        _add(d, rating)
        signals.upsert_signal(d, 'weather', 'temp_c', value_num=temp)
    db.session.commit()

    res = signals.correlate_signal_with_mood('weather', 'temp_c')
    assert res['kind'] == 'numeric'
    assert res['n'] == 4
    assert res['pearson'] == 1.0
    assert res['high_avg'] > res['low_avg']
    assert len(res['points']) == 4


def test_correlate_categorical_condition_excludes_deleted(app):
    rows = [('Clear', 8, False), ('Clear', 8, False),
            ('Rain', 4, False), ('Rain', 6, False),
            ('Rain', 1, True)]  # soft-deleted → must not count
    for i, (cond, rating, deleted) in enumerate(rows):
        d = date(2026, 7, 1 + i)
        _add(d, rating, deleted=deleted)
        signals.upsert_signal(d, 'weather', 'condition', value_text=cond)
    db.session.commit()

    res = signals.correlate_signal_with_mood('weather', 'condition')
    assert res['kind'] == 'categorical'
    groups = {g['label']: g for g in res['groups']}
    assert groups['Clear']['avg'] == 8.0 and groups['Clear']['count'] == 2
    assert groups['Rain']['avg'] == 5.0 and groups['Rain']['count'] == 2  # deleted excluded
    assert res['groups'][0]['label'] == 'Clear'  # sorted by avg desc


def test_correlate_empty_when_no_overlap(app):
    res = signals.correlate_signal_with_mood('weather', 'temp_c')
    assert res['kind'] == 'empty' and res['n'] == 0


# ── Geocoding (HTTP stubbed) ──────────────────────────────────

def test_geocode_city_parses(monkeypatch):
    monkeypatch.setattr(signals, '_http_get_json', lambda url: {'results': [
        {'latitude': 52.52, 'longitude': 13.41, 'name': 'Berlin',
         'admin1': 'Berlin', 'country': 'Germany'}]})
    loc = signals.geocode_city('Berlin')
    assert loc['lat'] == 52.52 and loc['lon'] == 13.41
    assert 'Berlin' in loc['label'] and 'Germany' in loc['label']


def test_geocode_city_none_when_no_results(monkeypatch):
    monkeypatch.setattr(signals, '_http_get_json', lambda url: {'results': []})
    assert signals.geocode_city('Nowhereville') is None
    assert signals.geocode_city('') is None


def test_geocode_picks_most_populous(monkeypatch):
    # A tiny village and the real city share a name → the city (higher
    # population) must win, not whichever the API returns first.
    monkeypatch.setattr(signals, '_http_get_json', lambda url: {'results': [
        {'latitude': 55.70, 'longitude': 74.14, 'name': 'Saratovo',
         'country': 'Russia', 'population': 6117},
        {'latitude': 51.54, 'longitude': 45.99, 'name': 'Saratov',
         'admin1': 'Saratov Oblast', 'country': 'Russia', 'population': 844858},
    ]})
    loc = signals.geocode_city('Saratov', lang='ru')
    assert loc['lat'] == 51.54
    assert loc['label'].startswith('Saratov')


# ── Config ────────────────────────────────────────────────────

def test_weather_config_roundtrip(app):
    assert signals.is_weather_enabled() is False
    assert signals.get_weather_location() is None

    signals.set_weather_config(True, lat=52.52, lon=13.41, label='Berlin, Germany')
    assert signals.is_weather_enabled() is True
    loc = signals.get_weather_location()
    assert loc['lat'] == 52.52 and loc['lon'] == 13.41 and loc['label'] == 'Berlin, Germany'

    # Disabling keeps the saved location so re-enabling needs no re-geocode.
    signals.set_weather_config(False)
    assert signals.is_weather_enabled() is False
    assert signals.get_weather_location()['lat'] == 52.52


def test_condition_label():
    assert signals.condition_label('Rain', 'ru') == 'Дождь'
    assert signals.condition_label('Rain', 'en') == 'Rain'
    assert signals.condition_label('Clear', 'ru') == 'Ясно'
    assert signals.condition_label('Unknown', 'ru') == 'Unknown'  # passthrough


# ── AI tool (lives in assistant.tools, reads the signals layer) ──────────────

def _seed_weather(app):
    rows = [(date(2026, 3, 1), 8, 18.0, 'Clear'), (date(2026, 3, 2), 9, 20.0, 'Clear'),
            (date(2026, 3, 3), 4, 3.0, 'Rain'), (date(2026, 3, 4), 5, 5.0, 'Rain')]
    for d, rating, temp, cond in rows:
        db.session.add(MoodEntry(date=d, rating=rating, note='x', deleted=False))
        signals.upsert_signal(d, 'weather', 'temp_c', value_num=temp)
        signals.upsert_signal(d, 'weather', 'condition', value_text=cond)
    db.session.commit()


def test_tool_weather_impact_without_data(app):
    from app.modules.assistant.tools import tool_weather_impact
    out = tool_weather_impact()
    assert 'Погодных данных пока нет' in out


def test_tool_weather_impact_with_data(app):
    from app.modules.assistant.tools import tool_weather_impact
    _seed_weather(app)
    out = tool_weather_impact()
    assert 'Температура' in out
    # localized condition labels, warm/clear ranked above cold/rain
    assert 'Ясно' in out and 'Дождь' in out


# ── Weather line chart (graphics route) ──────────────────────────────────────

def test_nice_step():
    from app.modules.graphics.routes import _nice_step
    assert _nice_step(0.18) == 0.2
    assert _nice_step(0.3) == 0.5
    assert _nice_step(0.9) == 1
    assert _nice_step(0) == 0.1


def test_weather_mood_by_temp():
    from app.modules.graphics.routes import _mood_by_numeric
    # mood rises with the signal value across a clear spread
    pts = [[float(t), max(1, min(10, 4 + t // 5))] for t in range(-6, 24)]
    c = _mood_by_numeric({'points': pts, 'overall_avg': 6})
    assert c is not None
    # connected polyline + a marker per binned point
    assert c['line_d'].startswith('M') and ' L' in c['line_d']
    assert len(c['points']) >= 3 and 0 < len(c['xticks']) <= len(c['points'])
    assert all('x' in p and 'y' in p and 'temp' in p and 'mood' in p for p in c['points'])
    # points sit inside the plot box; temps are sorted left→right
    assert all(c['pad_l'] - 1 <= p['x'] <= c['right_x'] + 1 for p in c['points'])
    assert [p['temp'] for p in c['points']] == sorted(p['temp'] for p in c['points'])
    # round y tick labels + happy/sad face anchors at top/bottom of the axis
    assert len(c['yticks']) >= 2
    assert c['face_top_y'] < c['face_bot_y']


def test_weather_mood_by_temp_insufficient():
    from app.modules.graphics.routes import _mood_by_numeric
    assert _mood_by_numeric({'points': [[5.0, 6], [5.0, 7]]}) is None    # too few
    assert _mood_by_numeric({'points': [[5.0, 6] for _ in range(20)]}) is None  # no spread
    assert _mood_by_numeric(None) is None    # tolerates missing correlation


def test_weather_stat_tiles(app):
    from app.modules.graphics.routes import _weather_stat_tiles
    temp = {'kind': 'numeric', 'high_avg': 7.5, 'low_avg': 4.5, 'pearson': 0.6,
            'overall_avg': 6, 'points': [], 'count': 50}
    precip = {'kind': 'numeric', 'points': [[0.0, 7], [0.0, 8], [5.0, 4], [3.0, 5]]}
    # Day counts are now part of the fixture: naming a best weather takes a
    # real sample behind it (see the thin-group case below).
    cond = {'kind': 'categorical', 'groups': [{'label': 'Clear', 'avg': 8, 'count': 40},
                                              {'label': 'Rain', 'avg': 4, 'count': 30}]}
    tiles = _weather_stat_tiles(temp, precip, cond)
    values = [tl['value'] for tl in tiles]
    assert '+3.0' in values                         # warm − cold = 7.5 − 4.5
    assert not any(v.startswith('+0.6') for v in values)   # no Pearson jargon tile
    # best-weather tile shows the happiest condition (localized), not a number
    assert tiles[-1]['value'] in ('Ясно', 'Clear')
    assert '8' in tiles[-1]['sub']                  # its average mood
    assert '40' in tiles[-1]['sub']                 # and the days behind it


def test_a_thin_condition_is_not_named_the_best_weather(app):
    """Four thunderstorms outranking eighty-six rainy days is arithmetic,
    not weather — the tile must not report it as a finding."""
    from app.modules.graphics.routes import _weather_stat_tiles
    temp = {'kind': 'numeric', 'high_avg': 7.5, 'low_avg': 4.5,
            'overall_avg': 6, 'points': [], 'count': 50}
    cond = {'kind': 'categorical',
            'groups': [{'label': 'Thunderstorm', 'avg': 6.0, 'count': 4},
                       {'label': 'Rain', 'avg': 5.8, 'count': 86}]}

    tiles = _weather_stat_tiles(temp, {}, cond)

    named = [tl['value'] for tl in tiles]
    assert 'Гроза' not in named and 'Thunderstorm' not in named
    assert any(v in ('Дождь', 'Rain') for v in named), \
        'the next weather with a real sample should take its place'
