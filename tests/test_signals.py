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
