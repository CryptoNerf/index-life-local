# index.life — Local mood diary
# https://github.com/CryptoNerf/index-life-local
# Copyright (C) 2026 Émile Alexanyan
#
# Licensed under AGPL-3.0 with additional terms per Section 7
# (preservation of author attribution, no misrepresentation of
# origin). See LICENSE and COPYRIGHT at the root of this project.
"""External daily signals + their correlation with mood.

A generic layer: every integration (weather now; steps, sleep, music later)
writes one row per (date, source, metric) into `daily_signals`, and one
correlation engine reads any of them against the day's mood rating. Adding a
source is a new provider function here — not a schema or analytics change.

Weather is provided by Open-Meteo (https://open-meteo.com): free, keyless,
privacy-friendly. The only thing that leaves the device is an approximate
lat/lon + date range, sent to open-meteo.com when the user has opted in.
Network access goes through one helper (`_http_get_json`) so it is easy to
stub in tests and easy to audit.
"""
import json
import logging
import threading
from datetime import date as date_type, timedelta
from urllib.parse import quote

from app import db
from app.models import MoodEntry, DailySignal, SyncMeta
from app.timeutil import utcnow

log = logging.getLogger(__name__)

# Coarse condition labels (the stored value_text is the English key, which is
# stable across UI languages; this maps it for display).
_CONDITION_LABELS = {
    'Clear':        {'ru': 'Ясно',     'en': 'Clear'},
    'Clouds':       {'ru': 'Облачно',  'en': 'Cloudy'},
    'Fog':          {'ru': 'Туман',    'en': 'Fog'},
    'Rain':         {'ru': 'Дождь',    'en': 'Rain'},
    'Snow':         {'ru': 'Снег',     'en': 'Snow'},
    'Thunderstorm': {'ru': 'Гроза',    'en': 'Thunderstorm'},
    'Other':        {'ru': 'Прочее',   'en': 'Other'},
}


def condition_label(key: str, lang: str = 'ru') -> str:
    """Localised label for a stored weather condition key (e.g. 'Rain')."""
    return _CONDITION_LABELS.get(key, {}).get(lang, key)

_HTTP_TIMEOUT = 15

# Number of recent days for which Open-Meteo's live forecast endpoint serves
# the past; older ranges fall to the historical archive endpoint.
_FORECAST_PAST_DAYS = 90


# ── HTTP (single audited entry point) ─────────────────────────

_ssl_ctx = None


def _get_ssl_context():
    """SSL context that can verify certificates even in a frozen build.

    PyInstaller bundles often ship without a usable CA store, so plain
    `urlopen` fails with CERTIFICATE_VERIFY_FAILED and weather silently never
    works. Prefer certifi's bundle (present in the bundled/venv deps); fall
    back to the platform default if certifi can't be imported.
    """
    global _ssl_ctx
    if _ssl_ctx is None:
        import ssl
        try:
            import certifi
            _ssl_ctx = ssl.create_default_context(cafile=certifi.where())
        except Exception:
            _ssl_ctx = ssl.create_default_context()
    return _ssl_ctx


def _http_get_json(url: str) -> dict | None:
    """GET a URL and parse JSON. Returns None on any failure (never raises)."""
    import urllib.request
    try:
        with urllib.request.urlopen(url, timeout=_HTTP_TIMEOUT,
                                    context=_get_ssl_context()) as resp:
            return json.loads(resp.read().decode('utf-8'))
    except Exception as exc:
        log.warning('signals: HTTP GET failed (%s): %s', url.split('?', 1)[0], exc)
        return None


# ── Weather: Open-Meteo ───────────────────────────────────────

def _wmo_condition(code) -> str | None:
    """Map a WMO weather code to a coarse condition label for grouping."""
    if code is None:
        return None
    try:
        c = int(code)
    except (TypeError, ValueError):
        return None
    if c == 0:
        return 'Clear'
    if c in (1, 2, 3):
        return 'Clouds'
    if c in (45, 48):
        return 'Fog'
    if c in (51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 80, 81, 82):
        return 'Rain'
    if c in (71, 73, 75, 77, 85, 86):
        return 'Snow'
    if c in (95, 96, 99):
        return 'Thunderstorm'
    return 'Other'


def _weather_url(lat: float, lon: float, start: date_type, end: date_type) -> str:
    daily = 'temperature_2m_mean,precipitation_sum,weather_code'
    use_archive = start < (date_type.today() - timedelta(days=_FORECAST_PAST_DAYS))
    base = ('https://archive-api.open-meteo.com/v1/archive' if use_archive
            else 'https://api.open-meteo.com/v1/forecast')
    return (
        f'{base}?latitude={float(lat)}&longitude={float(lon)}'
        f'&start_date={start.isoformat()}&end_date={end.isoformat()}'
        f'&daily={daily}&timezone=auto'
    )


def fetch_weather(lat: float, lon: float, start: date_type,
                  end: date_type) -> dict[date_type, dict]:
    """Fetch daily weather for [start, end]. Returns {date: {temp_c, precip_mm,
    condition}}. Empty dict on failure (logged, never raises)."""
    data = _http_get_json(_weather_url(lat, lon, start, end))
    daily = (data or {}).get('daily') or {}
    times = daily.get('time') or []
    temps = daily.get('temperature_2m_mean') or []
    precs = daily.get('precipitation_sum') or []
    codes = daily.get('weather_code') or []

    out: dict[date_type, dict] = {}
    for i, t in enumerate(times):
        try:
            d = date_type.fromisoformat(t)
        except (ValueError, TypeError):
            continue
        out[d] = {
            'temp_c': temps[i] if i < len(temps) else None,
            'precip_mm': precs[i] if i < len(precs) else None,
            'condition': _wmo_condition(codes[i] if i < len(codes) else None),
        }
    return out


def record_weather(lat: float, lon: float, start: date_type,
                   end: date_type) -> int:
    """Fetch weather for the range and upsert it into daily_signals.

    Returns the number of metric rows written. Commits once at the end.
    """
    weather = fetch_weather(lat, lon, start, end)
    written = 0
    for d, metrics in weather.items():
        if metrics.get('temp_c') is not None:
            upsert_signal(d, 'weather', 'temp_c', value_num=float(metrics['temp_c']))
            written += 1
        if metrics.get('precip_mm') is not None:
            upsert_signal(d, 'weather', 'precip_mm', value_num=float(metrics['precip_mm']))
            written += 1
        if metrics.get('condition'):
            upsert_signal(d, 'weather', 'condition', value_text=metrics['condition'])
            written += 1
    if written:
        db.session.commit()
    return written


def record_weather_async(app, start: date_type, end: date_type) -> None:
    """Best-effort background weather fetch for [start, end].

    No-op when weather is disabled or unconfigured; never blocks or raises in
    the caller. Used by the entry-save trigger and the initial backfill.
    """
    def _run():
        with app.app_context():
            try:
                if not is_weather_enabled():
                    return
                loc = get_weather_location()
                if not loc:
                    return
                n = record_weather(loc['lat'], loc['lon'], start, end)
                if n:
                    log.info('Weather: recorded %d signal rows for %s..%s',
                             n, start, end)
            except Exception:
                log.warning('Weather fetch failed', exc_info=True)
                try:
                    db.session.rollback()
                except Exception:
                    pass

    threading.Thread(target=_run, daemon=True).start()


def backfill_weather(lat: float, lon: float, start: date_type,
                     end: date_type) -> int:
    """Record weather across the whole [start, end] span.

    Recent days go through the forecast endpoint (the archive lags ~5 days),
    older days through the historical archive, chunked to keep each request
    bounded. Idempotent — upserts in place. Returns the number of rows.
    """
    if start > end:
        return 0
    total = 0
    forecast_cut = date_type.today() - timedelta(days=_FORECAST_PAST_DAYS)

    # Recent window via the forecast endpoint (covers right up to today).
    recent_start = max(start, forecast_cut)
    if recent_start <= end:
        total += record_weather(lat, lon, recent_start, end)

    # Older history via the archive endpoint, chunked by ~one year.
    older_end = min(end, forecast_cut - timedelta(days=1))
    cur = start
    while cur <= older_end:
        chunk_end = min(older_end, cur + timedelta(days=365))
        total += record_weather(lat, lon, cur, chunk_end)
        cur = chunk_end + timedelta(days=1)
    return total


def backfill_all_weather_async(app) -> None:
    """Background: backfill weather for the full span of journaled days.

    No-op when weather is off/unconfigured or the diary is empty. Lets a user
    with months of history fill in the whole mood↔weather correlation, not
    just the days since they enabled weather.
    """
    def _run():
        with app.app_context():
            try:
                if not is_weather_enabled():
                    return
                loc = get_weather_location()
                if not loc:
                    return
                first = (db.session.query(db.func.min(MoodEntry.date))
                         .filter(MoodEntry.deleted == False)  # noqa: E712
                         .scalar())
                if first is None:
                    return
                today = date_type.today()
                n = backfill_weather(loc['lat'], loc['lon'], first, today)
                log.info('Weather backfill: %d rows over %s..%s', n, first, today)
            except Exception:
                log.warning('Weather backfill failed', exc_info=True)
                try:
                    db.session.rollback()
                except Exception:
                    pass

    threading.Thread(target=_run, daemon=True).start()


def _geocode_search(name: str, lang: str) -> list:
    url = (f'https://geocoding-api.open-meteo.com/v1/search?name={quote(name)}'
           f'&count=10&language={lang}&format=json')
    data = _http_get_json(url)
    return (data or {}).get('results') or []


def geocode_city(name: str, lang: str = 'en') -> dict | None:
    """Resolve a city name to {lat, lon, label} via Open-Meteo geocoding.

    Two things that the naive `count=1&language=en` version got wrong:

    * A Cyrillic query like "Москва" only matches with language=ru, so we
      search in the user's UI language first and fall back to English (and
      ru), which makes both "Саратов" and "Saratov" resolve.
    * Among matches we pick the most populous place, so "Саратов" lands on
      the city (pop ~845k) rather than a tiny same-named village.
    """
    name = (name or '').strip()
    if not name:
        return None
    tried: list[str] = []
    for lg in (lang, 'en', 'ru'):
        if lg in tried:
            continue
        tried.append(lg)
        results = _geocode_search(name, lg)
        if not results:
            continue
        best = max(results, key=lambda r: r.get('population') or 0)
        lat, lon = best.get('latitude'), best.get('longitude')
        if lat is None or lon is None:
            continue
        label = ', '.join(p for p in (best.get('name'), best.get('admin1'),
                                      best.get('country')) if p)
        return {'lat': float(lat), 'lon': float(lon), 'label': label}
    return None


# ── Signal upsert ─────────────────────────────────────────────

def upsert_signal(date, source: str, metric: str, value_num: float | None = None,
                  value_text: str | None = None) -> DailySignal:
    """Insert or update the single row for (date, source, metric).

    Does NOT commit — the caller batches and commits (see record_weather)."""
    row = DailySignal.query.filter_by(date=date, source=source, metric=metric).first()
    if row is None:
        row = DailySignal(date=date, source=source, metric=metric)
        db.session.add(row)
    row.value_num = value_num
    row.value_text = value_text
    row.updated_at = utcnow()
    return row


# ── Correlation with mood ─────────────────────────────────────

def _pearson(xs: list[float], ys: list[float]) -> float | None:
    n = len(xs)
    if n < 2:
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    vx = sum((x - mx) ** 2 for x in xs)
    vy = sum((y - my) ** 2 for y in ys)
    if vx == 0 or vy == 0:
        return None
    return round(cov / (vx ** 0.5 * vy ** 0.5), 3)


def correlate_signal_with_mood(source: str, metric: str) -> dict:
    """Relate one signal to mood across days that have both.

    Numeric metrics (temp_c, precip_mm) → Pearson r + a below/above-median
    mood split + raw (signal, rating) points for a scatter. Categorical ones
    (condition) → average mood per label. Soft-deleted entries are excluded.
    """
    rows = (db.session.query(MoodEntry.rating, DailySignal.value_num,
                             DailySignal.value_text)
            .join(DailySignal, DailySignal.date == MoodEntry.date)
            .filter(MoodEntry.deleted == False,  # noqa: E712
                    DailySignal.source == source, DailySignal.metric == metric)
            .all())

    ratings = [r for (r, _vn, _vt) in rows]
    n = len(ratings)
    result = {
        'source': source, 'metric': metric, 'n': n,
        'overall_avg': round(sum(ratings) / n, 2) if n else None,
    }
    if n == 0:
        result['kind'] = 'empty'
        return result

    nums = [(vn, r) for (r, vn, _vt) in rows if vn is not None]
    if len(nums) >= 2 and len(nums) >= n * 0.5:
        result['kind'] = 'numeric'
        result['count'] = len(nums)
        result['pearson'] = _pearson([v for v, _ in nums], [r for _, r in nums])
        ordered = sorted(nums)  # by signal value
        mid = len(ordered) // 2
        low = [r for _v, r in ordered[:mid]]
        high = [r for _v, r in ordered[len(ordered) - mid:]]
        result['low_avg'] = round(sum(low) / len(low), 2) if low else None
        result['high_avg'] = round(sum(high) / len(high), 2) if high else None
        result['points'] = [[round(v, 2), r] for v, r in nums]
    else:
        result['kind'] = 'categorical'
        groups: dict[str, list[int]] = {}
        for (r, _vn, vt) in rows:
            if vt:
                groups.setdefault(vt, []).append(r)
        result['groups'] = sorted(
            ({'label': k, 'avg': round(sum(v) / len(v), 2), 'count': len(v)}
             for k, v in groups.items()),
            key=lambda g: -g['avg'],
        )
    return result


# ── Weather config (device-local, stored in sync_meta) ────────

def _meta_get(key: str) -> str | None:
    row = db.session.get(SyncMeta, key)
    return row.value if row else None


def _meta_set(key: str, value: str) -> None:
    row = db.session.get(SyncMeta, key)
    if row:
        row.value = value
    else:
        db.session.add(SyncMeta(key=key, value=value))


def is_weather_enabled() -> bool:
    return _meta_get('weather_enabled') == 'true'


def get_weather_location() -> dict | None:
    lat, lon = _meta_get('weather_lat'), _meta_get('weather_lon')
    if lat is None or lon is None:
        return None
    try:
        return {'lat': float(lat), 'lon': float(lon),
                'label': _meta_get('weather_label') or ''}
    except (TypeError, ValueError):
        return None


def set_weather_config(enabled: bool, lat: float | None = None,
                       lon: float | None = None, label: str | None = None) -> None:
    """Persist weather opt-in + location. Commits."""
    _meta_set('weather_enabled', 'true' if enabled else 'false')
    if lat is not None:
        _meta_set('weather_lat', str(float(lat)))
    if lon is not None:
        _meta_set('weather_lon', str(float(lon)))
    if label is not None:
        _meta_set('weather_label', label)
    db.session.commit()
