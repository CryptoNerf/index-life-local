"""Minimal i18n layer — JSON catalogs + a context processor.

Why a hand-rolled solution instead of Flask-Babel: the app is a single
small Flask process, translations are short UI strings, and we want to
avoid a .po/.mo compile step. A flat JSON catalog per language is
enough — the function below resolves a key by:

    user-pref language (UserProfile.language) → 'ru' fallback → raw key

Catalogs live in `app/translations/<lang>.json` and are loaded ONCE at
import time. To add a new key:
    1) put it in `ru.json`
    2) put it in `en.json`
    3) reference it from a template as {{ t('key.name') }}

`t()` is also exposed to Jinja via the context processor so templates
don't need to import anything.

For JS-side translations, the context processor exposes `js_translations`
(the full active-lang dict) which can be JSON-dumped into a `<script>`
tag and read by client code.

Reading the language preference:
    1) UserProfile.language — the persisted choice (single-user app).
    2) 'ru' if the row is missing or DB read fails.

This is wrapped in try/except so a missing column / broken DB never
breaks page rendering.
"""
import json
import logging
from pathlib import Path

from flask import g, request

log = logging.getLogger(__name__)

SUPPORTED_LANGS = ('ru', 'en')
DEFAULT_LANG = 'ru'

# Loaded once at import. Reloading requires a process restart, which is
# fine — translations only change when developers edit the JSON files.
_CATALOGS: dict[str, dict] = {}


def _load_catalogs():
    """Load every `<lang>.json` from app/translations/ into _CATALOGS."""
    base = Path(__file__).parent / 'translations'
    for lang in SUPPORTED_LANGS:
        path = base / f'{lang}.json'
        try:
            with open(path, 'r', encoding='utf-8') as f:
                _CATALOGS[lang] = json.load(f)
        except FileNotFoundError:
            log.warning('i18n: catalog %s missing — falling back to key', path)
            _CATALOGS[lang] = {}
        except Exception as exc:
            log.error('i18n: failed to load %s: %s', path, exc)
            _CATALOGS[lang] = {}


_load_catalogs()


def get_current_lang() -> str:
    """Resolve the active language for the current request.

    Caches on Flask's `g` so a single request that calls `t()` dozens of
    times doesn't hit the DB more than once.
    """
    # Cache on Flask `g` so repeated `t()` calls within one request reuse the value.
    try:
        cached = getattr(g, '_i18n_lang', None)
        if cached:
            return cached
    except RuntimeError:
        # Outside a request context (e.g. CLI / startup) → just return default.
        return DEFAULT_LANG

    lang = DEFAULT_LANG
    try:
        from app.models import UserProfile
        row = UserProfile.query.first()
        if row and row.language in SUPPORTED_LANGS:
            lang = row.language
    except Exception as exc:
        log.debug('i18n: could not read UserProfile.language (%s)', exc)

    g._i18n_lang = lang
    return lang


def t(key: str, lang: str | None = None, **kwargs) -> str:
    """Translate `key` for the given language (or the current user's).

    Falls back through:
      requested lang → DEFAULT_LANG → key itself
    so a missing string never crashes — it shows up as the raw key for
    easy spotting in the UI.

    Optional kwargs are substituted via Python str.format() so callers
    can do `t('greeting.hello', name='Mary')` against a catalog value of
    `"hello, {name}"`.
    """
    if lang is None:
        lang = get_current_lang()
    cat = _CATALOGS.get(lang) or {}
    value = cat.get(key)
    if value is None:
        # Fall back to the default-language string before giving up.
        if lang != DEFAULT_LANG:
            value = _CATALOGS.get(DEFAULT_LANG, {}).get(key)
        if value is None:
            return key
    if kwargs:
        try:
            return value.format(**kwargs)
        except (KeyError, IndexError):
            return value
    return value


def get_catalog(lang: str | None = None) -> dict:
    """Return the entire dict for a language — used to embed translations
    for client-side JS without making a network round-trip per string.
    """
    if lang is None:
        lang = get_current_lang()
    return _CATALOGS.get(lang) or {}


def register_context_processor(app):
    """Expose `t`, `current_lang`, `supported_langs`, and `js_translations`
    to every template render.
    """
    @app.context_processor
    def inject_i18n():
        return {
            't': t,
            'current_lang': get_current_lang(),
            'supported_langs': SUPPORTED_LANGS,
            # JSON-serializable dict for embedding in <script> tags.
            'js_translations': get_catalog(),
        }
