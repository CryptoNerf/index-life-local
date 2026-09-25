# index.life — Local mood diary
# https://github.com/CryptoNerf/index-life-local
# Copyright (C) 2026 Émile Alexanyan
#
# Licensed under AGPL-3.0 with additional terms per Section 7
# (preservation of author attribution, no misrepresentation of
# origin). See LICENSE and COPYRIGHT at the root of this project.
"""A symbol in each day's cell, chosen per rating.

Anything the user likes: the rating itself, a crying face for a one and a
grinning one for a ten, a letter, a dot. The ten symbols are stored as one
JSON list under `cube-symbols`, because an empty symbol ("nothing for a
five") has to be storable and the settings layer drops empty strings.

The symbols are written into the page by the calendar template, where
Jinja escapes them — they never reach CSS or JavaScript as code.
"""
from __future__ import annotations

import json
import unicodedata

from . import rating_scale
from .defaults import DEFAULTS

# Long enough for an emoji with a skin tone or a ZWJ sequence, short enough
# that nobody pastes a sentence into a fifteen-pixel square.
MAX_SYMBOL_CHARS = 8

# Symbols longer than this (in code points) get the smaller font, so "10"
# fits beside "1" and "ok" but a three-letter word still does not overflow.
_LONG_AT = 3


def is_enabled(settings: dict) -> bool:
    return settings.get('cube-symbols-enabled',
                        DEFAULTS['cube-symbols-enabled']) == 'true'


def parse(value) -> list[str] | None:
    """The stored JSON as ten strings, or None if it is not a valid list."""
    if not isinstance(value, str):
        return None
    try:
        data = json.loads(value)
    except (ValueError, TypeError):
        return None
    if not isinstance(data, list) or len(data) != 10:
        return None
    out = []
    for item in data:
        if not isinstance(item, str) or len(item) > MAX_SYMBOL_CHARS:
            return None
        # Control and format characters other than the joiners emoji need
        # (ZWJ, variation selectors) have no business in a cell.
        for ch in item:
            cat = unicodedata.category(ch)
            if cat == 'Cc' or (cat == 'Cf' and ch not in '‍︎️'):
                return None
        out.append(item.strip())
    return out


def is_valid(value) -> bool:
    return parse(value) is not None


def symbols(settings: dict) -> list[str]:
    """The ten symbols in effect, rating 1 first."""
    return (parse(settings.get('cube-symbols'))
            or parse(DEFAULTS['cube-symbols']))


def for_template(settings: dict) -> dict[int, str] | None:
    """{rating: symbol} for the calendar template, or None when off.

    Ratings whose symbol is empty are left out, so the template only has
    to ask whether a day's rating is in the dict.
    """
    if not is_enabled(settings):
        return None
    return {i + 1: s for i, s in enumerate(symbols(settings)) if s}


def _luma(rgb) -> float:
    r, g, b = rgb
    return r * 0.299 + g * 0.587 + b * 0.114


def _hex_rgb(value: str) -> tuple[int, int, int]:
    s = (value or '').strip().lstrip('#')
    if len(s) == 3:
        s = ''.join(c * 2 for c in s)
    try:
        return (int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16))
    except ValueError:
        return (0, 0, 0)


def css_rules(settings: dict) -> str:
    """Layout for cells that carry a symbol, and a readable symbol colour.

    The colour is worked out per rating from what the cell is actually
    painted with — the rating scale when days are coloured by rating, the
    filled-day colour otherwise, the empty-day colour when the fill is
    hidden — so a black "7" never lands on a black square. Emoji carry
    their own colours and ignore it.
    """
    if not is_enabled(settings):
        return ''
    hide_fill = settings.get('cube-symbols-hide-fill',
                             DEFAULTS['cube-symbols-hide-fill']) == 'true'
    rules = [
        # container-type lets the font follow the cell, which is 15px on a
        # desktop and larger on phones; the px size is the fallback.
        'html .cube.has-sym{display:inline-flex;align-items:center;'
        'justify-content:center;overflow:hidden;text-decoration:none;'
        'line-height:1;container-type:size;vertical-align:top;}',
        'html .cube-sym{font-size:10px;font-size:66cqmin;white-space:nowrap;'
        'pointer-events:none;font-family:var(--font-body,"Times New Roman",Times,serif);}',
        'html .cube-sym.long{font-size:7px;font-size:44cqmin;}',
    ]
    if hide_fill:
        rules.append('html .cube.filled.has-sym,html .cube.hovered.has-sym'
                     '{background:var(--cube-empty-color,#fff);}')
    # The day page's rating row shows every rating's symbol as a key; the ones
    # not chosen are dimmed, which also marks the choice when the fill under
    # symbols is switched off.
    rules.append('html .cubes-row .cube.has-sym:not(.filled):not(.hovered) .cube-sym'
                 '{opacity:.35;}')
    scale_on = rating_scale.is_enabled(settings)
    stops = rating_scale.stops(settings) if scale_on else None
    filled = _hex_rgb(settings.get('cube-filled-color', DEFAULTS['cube-filled-color']))
    empty = _hex_rgb(settings.get('cube-empty-color', DEFAULTS['cube-empty-color']))
    # An unfilled cell (the day page's rating row) sits on the empty colour.
    rules.append('html .cube.has-sym .cube-sym{color:%s;}'
                 % ('#ffffff' if _luma(empty) < 128 else '#000000'))
    for rating in range(1, 11):
        if hide_fill:
            under = empty
        elif scale_on:
            under = rating_scale.rgb_at(stops, rating)
        else:
            under = filled
        colour = '#ffffff' if _luma(under) < 128 else '#000000'
        rules.append('html .cube.filled.r%d .cube-sym,html .cube.hovered.r%d .cube-sym'
                     '{color:%s;}' % (rating, rating, colour))
    return '\n'.join(rules)


def is_long(symbol: str) -> bool:
    return len(symbol) >= _LONG_AT
