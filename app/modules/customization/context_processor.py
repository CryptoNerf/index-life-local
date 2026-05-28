# index.life — Local mood diary
# https://github.com/CryptoNerf/index-life-local
# Copyright (C) 2026 Émile Alexanyan
#
# Licensed under AGPL-3.0 with additional terms per Section 7
# (preservation of author attribution, no misrepresentation of
# origin). See LICENSE and COPYRIGHT at the root of this project.
"""Inject customization CSS variables into every template.

Renders a tiny `<style>` block with `:root { --name: value; ... }`
which Jinja templates emit in their `<head>`. Only user-changed values
are emitted — unchanged keys stay implicit and fall through to the
`var(--name, default)` fallback baked into the existing CSS rules.

Composite values are computed here, NOT stored verbatim:
  * page background (`--bg-image`) is composed from `bg-type` plus
    its sub-fields (gradient stops or image filename)
  * fonts (`--font-body`, `--font-heading`) are looked up in the
    server-side catalog by their `font-*-id` setting; the special
    'custom' id additionally emits a @font-face for the user's
    uploaded font file.

A `<link rel="stylesheet">` to the bundled fonts.css is included so
all 8 fonts are available across all pages without per-template wiring.

DB read is wrapped in try/except: the customization module must never
break page rendering. If anything goes wrong we silently emit nothing.
"""
import json
import logging
from markupsafe import Markup

from .defaults import DEFAULTS

log = logging.getLogger(__name__)


# Keys that exist purely as metadata for the settings UI — they must
# NOT be emitted as raw CSS variables. The composer below reads them
# and produces the actual CSS values.
_METADATA_KEYS = {
    'bg-type',
    'bg-gradient-from', 'bg-gradient-to', 'bg-gradient-angle',
    'bg-image-filename',
    'font-body-id', 'font-heading-id', 'custom-font-filename',
    'notes-use-body-font',
    'auto-invert-text',
    # Mosaic settings — JS reads them via window.__CZ_MOSAIC__ rather
    # than CSS variables (per-cube positioning needs DOM measurement).
    'mosaic-enabled', 'mosaic-filled-filename',
    'mosaic-empty-mode', 'mosaic-empty-filename',
    'mosaic-empty-grad-from', 'mosaic-empty-grad-to', 'mosaic-empty-grad-angle',
    'mosaic-empty-color',
}

# Per-chart keys are emitted via _chart_overrides as explicit class
# rules, NOT as raw `--chart-color: ...` CSS variables. So they belong
# to the metadata set (excluded from the `:root { --k: v }` block).
from .chart_schema import ALL_CONTROLS as _CHART_CONTROLS  # noqa: E402
_METADATA_KEYS.update(_CHART_CONTROLS.keys())


def _load_user_settings() -> dict:
    """Read the user_customization row's settings_json.

    Returns only known keys with non-empty string values. Returns {}
    on any DB/JSON failure so callers no-op safely.
    """
    try:
        from app.models import UserCustomization
        row = UserCustomization.query.first()
        if not row or not row.settings_json:
            return {}
        data = json.loads(row.settings_json)
        if not isinstance(data, dict):
            return {}
        return {
            k: v for k, v in data.items()
            if k in DEFAULTS and isinstance(v, str) and v.strip()
        }
    except Exception as exc:
        log.debug('customization: failed to read settings (%s) — emitting nothing', exc)
        return {}


def _compose_font(settings: dict, key: str) -> str | None:
    """Compute --font-body / --font-heading from `font-*-id`.

    Returns None when the user is on the 'times' default or hasn't set
    anything — letting the CSS fallback in `var(--font-body, ...)`
    keep the historic look. For 'custom' returns the family name
    'Custom' which matches the @font-face declaration emitted below.
    """
    from .fonts_catalog import family_for_id
    font_id = settings.get(key)
    if not font_id or font_id == 'times':
        return None
    if font_id == 'custom':
        # Only useful if a custom font has actually been uploaded.
        if settings.get('custom-font-filename'):
            return "'Custom', sans-serif"
        return None
    return family_for_id(font_id)


def _custom_font_face_rule(settings: dict) -> str:
    """Build an @font-face rule for an uploaded custom font.

    Empty string when there's no custom font in use. The 'Custom'
    family is referenced from `_compose_font` when the user picks the
    'custom' font id.
    """
    fn = settings.get('custom-font-filename')
    if not fn:
        return ''
    body_id = settings.get('font-body-id')
    heading_id = settings.get('font-heading-id')
    if 'custom' not in (body_id, heading_id):
        return ''
    # Format hint helps the browser pick a parser; we don't strictly
    # know the ext from filename here without parsing — let the browser
    # auto-detect by omitting `format()`.
    return (
        '@font-face {'
        '  font-family: "Custom";'
        '  font-style: normal;'
        '  font-weight: normal;'
        '  font-display: swap;'
        f'  src: url("/customization/uploads/{fn}");'
        '}'
    )


def _compose_bg_image(settings: dict) -> str | None:
    """Compute the effective `--bg-image` value from metadata fields.

    Returns None if the user hasn't configured anything beyond the
    default solid-color background — in which case the CSS rule's
    fallback (`var(--bg-image, none)`) keeps a clean default.
    """
    bg_type = settings.get('bg-type')
    if bg_type == 'gradient':
        a = settings.get('bg-gradient-from', '#ffffff')
        b = settings.get('bg-gradient-to', '#dddddd')
        ang = settings.get('bg-gradient-angle', '180deg')
        return f'linear-gradient({ang}, {a}, {b})'
    if bg_type == 'image':
        fn = settings.get('bg-image-filename', '')
        if not fn:
            return None
        # URL is served by serve_upload(); filename is restricted by
        # _FILENAME_RE in routes.py so this is safe to interpolate.
        return f'url("/customization/uploads/{fn}")'
    return None  # solid color or unset


def _hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    """Parse `#rrggbb` → (r,g,b). Falls back to black on bad input."""
    if not isinstance(hex_color, str):
        return (0, 0, 0)
    s = hex_color.strip().lstrip('#')
    if len(s) == 3:
        s = ''.join(c * 2 for c in s)
    if len(s) != 6:
        return (0, 0, 0)
    try:
        return (int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16))
    except ValueError:
        return (0, 0, 0)


def _parse_css_color(value: str) -> tuple[int, int, int, float] | None:
    """Best-effort parser for the colour formats users actually pick:
    `#rgb`, `#rrggbb`, `rgb(r,g,b)`, `rgba(r,g,b,a)`. Returns (r,g,b,a)
    where a is 0..1, or None when the value doesn't match — we never
    raise so a stray free-text overlay can't crash render.
    """
    if not isinstance(value, str):
        return None
    s = value.strip().lower()
    if not s or s == 'transparent':
        return None
    if s.startswith('#'):
        r, g, b = _hex_to_rgb(s)
        return (r, g, b, 1.0)
    import re as _re
    m = _re.match(r'rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*(?:,\s*([\d.]+)\s*)?\)', s)
    if not m:
        return None
    try:
        r, g, b = int(m.group(1)), int(m.group(2)), int(m.group(3))
        a = float(m.group(4)) if m.group(4) is not None else 1.0
        return (r, g, b, a)
    except ValueError:
        return None


def _effective_bg_rgb(settings: dict) -> tuple[int, int, int] | None:
    """Pick a single (r,g,b) that best represents what the user sees
    behind the page text.

    Priority chain:
      1. bg-type='color' → bg-color.
      2. bg-type='gradient' → midpoint between from / to.
      3. bg-type='image' → None (can't sample a photo server-side, so
         auto-invert stays off — manual text-color wins).

    Returns None when no decision can be made.
    """
    bg_type = settings.get('bg-type', 'color')
    if bg_type == 'color':
        return _hex_to_rgb(settings.get('bg-color', '#ffffff'))
    if bg_type == 'gradient':
        a = _hex_to_rgb(settings.get('bg-gradient-from', '#ffffff'))
        b = _hex_to_rgb(settings.get('bg-gradient-to',   '#dddddd'))
        return ((a[0] + b[0]) // 2, (a[1] + b[1]) // 2, (a[2] + b[2]) // 2)
    return None


def _luma(rgb: tuple[int, int, int]) -> float:
    """ITU-R BT.601 luminance — cheap and good enough to decide
    'is this bg dark enough that black text would disappear?'.
    """
    r, g, b = rgb
    return r * 0.299 + g * 0.587 + b * 0.114


def _auto_invert_overrides(settings: dict) -> tuple[str | None, str | None]:
    """If `auto-invert-text` is enabled, pick text + muted colours that
    contrast with the effective background. Returns (text, muted) or
    (None, None) when auto-invert is off or we can't infer a background.
    """
    if settings.get('auto-invert-text') != 'true':
        return (None, None)
    rgb = _effective_bg_rgb(settings)
    if rgb is None:
        return (None, None)
    if _luma(rgb) < 128:
        # Dark background — light text. Muted is a slightly darker white
        # so it still reads as a secondary tone, not pure body text.
        return ('#ffffff', '#cccccc')
    # Light background — keep the classic dark stack.
    return ('#000000', '#666666')


# Per-chart override map: each schema key → (selector, css-property).
# Some keys produce multiple rules (e.g. river-line affects both stroke
# colour and stroke-width on the same selector). The function below
# walks this map and emits exactly the rules a given user's settings need.
#
# When a key has type 'unit' and refers to a fill, the colour is read
# from the matching `*-color` companion key (or the global chart-color
# fallback) so the resulting `rgba()` is meaningful. See
# `_chart_unit_overrides` for that case.
_CHART_OVERRIDE_MAP: dict[str, tuple[str, str]] = {
    # ── River ─────────────────────────────────────────
    'river-line-color':   ('.river-line',     'stroke'),
    'river-line-width':   ('.river-line',     'stroke-width'),
    'river-dot-color':    ('.river-raw-dot',  'fill'),
    'river-today-color':  ('.today-line',     'stroke'),
    'river-grid-color':   ('.axis-faint',     'stroke'),
    # river-area-color / river-area-opacity composed to rgba — handled separately.
    # ── Spiral ────────────────────────────────────────
    'spiral-dot-color':    ('.spiral-dot',     'fill'),
    'spiral-guide-color':  ('.spiral-guide',   'stroke'),
    'spiral-today-color':  ('.spiral-today',   'stroke'),
    'spiral-month-color':  ('.spiral-month-mark,.spiral-month-label', 'fill'),
    # ── Rhythm ────────────────────────────────────────
    'rhythm-cell-color':    ('.rhythm-cell',           'fill'),
    'rhythm-empty-color':   ('.rhythm-cell.empty',     'fill'),
    'rhythm-weekend-color': ('.rhythm-weekend-rule',   'stroke'),
    # ── Rose ──────────────────────────────────────────
    'rose-petal-color':  ('.rose-petal',         'fill'),
    'rose-empty-color':  ('.rose-petal.empty',   'fill'),
    'rose-ref-color':    ('.rose-ref',           'stroke'),
    # ── Ridgeline ─────────────────────────────────────
    'ridge-line-color':     ('.ridge-line',     'stroke'),
    'ridge-baseline-color': ('.ridge-baseline', 'stroke'),
    # ridge-fill-color / ridge-fill-opacity → rgba() handled separately.
    # ── Overview ──────────────────────────────────────
    'overview-heat-color':   ('.heat-cell:not(.heat-empty)', 'fill'),
    'overview-empty-color':  ('.heat-empty',                 'fill'),
    'overview-bar-color':    ('.bar',                        'fill'),
    'overview-today-color':  ('.heat-today',                 'stroke'),
    # ── Activities zoom — circles use fill-opacity for the data shade
    #   so the base `fill` colour is themable via CSS class. Stroke is
    #   moved to CSS too (template no longer sets it inline in JS).
    'az-circle-color':  ('.az-activity-circle,.az-mention-circle', 'fill'),
    'az-circle-stroke': ('.az-circle',                              'stroke'),
    'az-canvas-bg':     ('.az-canvas',                              'background'),
    'az-label-color':   ('.az-label',                               'fill'),
}


def _chart_overrides(settings: dict) -> str:
    """Emit explicit CSS rules for chart classes when the user has
    customized chart appearance — both the global `chart-color` /
    `chart-grid-color` fallbacks and the per-chart keys defined in
    `chart_schema.CHARTS`.

    Why this lives in the inline `<style>` block instead of relying
    purely on `var(--chart-color, ...)` inside insights.css:
      * Browsers aggressively cache static CSS files; inline rules
        ship with each page render so they always reflect the latest
        settings (no hard-reload needed).
      * Some chart options (line-width, area-opacity, per-chart
        fill colours) don't fit cleanly into a single CSS variable.

    Specificity tie with the original .axis / .river-line rules in
    insights.css is broken by *order*: the inline `<style>` block is
    placed in `<head>` after the CSS link, so its rules win.
    """
    pieces = []

    # ── Global "set everything" fallbacks ─────────────────
    # Apply only to surfaces that don't have a per-chart override.
    # (We can't easily check that in CSS specificity terms because
    # both rules have the same specificity; instead we emit the
    # global rule first, then per-chart rules later — last wins.)
    if 'chart-color' in settings:
        c = settings['chart-color']
        pieces.append(
            f'.axis,.river-line,.ridge-line{{stroke:{c};}}'
            f'.river-raw-dot,.bar,.spiral-dot,.rhythm-cell,'
            f'.rose-petal,.heat-cell,'
            f'.az-activity-circle,.az-mention-circle{{fill:{c};}}'
        )
    if 'chart-grid-color' in settings:
        c = settings['chart-grid-color']
        pieces.append(
            f'.axis-faint,.spiral-guide,.heat-empty,.rose-ref,'
            f'.ridge-baseline{{stroke:{c};}}'
        )

    # ── Per-chart keys via the override map ──────────────
    for key, (selector, prop) in _CHART_OVERRIDE_MAP.items():
        if key in settings:
            pieces.append(f'{selector}{{{prop}:{settings[key]};}}')

    # Per-chart color keys are ALSO emitted as :root CSS variables so
    # peripheral elements (legend dots, swatches, landing-page card
    # miniatures) can pick them up via `var(--<key>, …)` and stay in
    # sync with the chart proper. We include ALL color-type per-chart
    # keys from the schema — including those (river-area-color,
    # ridge-fill-color) that the override map handles via `_composed_fill`
    # rather than a simple class rule, since meta-UI still needs the
    # raw colour to render with.
    from .chart_schema import ALL_CONTROLS as _CHART_CTRLS_FOR_VARS
    _color_chart_keys = {
        k for k, ctrl in _CHART_CTRLS_FOR_VARS.items() if ctrl.get('type') == 'color'
    }
    chart_vars = []
    for key in settings:
        if key in _color_chart_keys and _is_color_value(settings[key]):
            chart_vars.append(f'  --{key}: {settings[key]};')
    if chart_vars:
        pieces.append(':root {\n' + '\n'.join(chart_vars) + '\n}')

    # ── Composed rgba() rules for area fills ─────────────
    # The river area and ridgeline ridge fills want a base colour with
    # a separate opacity. We compose rgba() so the user can pick a
    # base colour AND a strength independently.
    pieces.append(
        _composed_fill('.river-area',
                       settings.get('river-area-color'),
                       settings.get('river-area-opacity'))
    )
    pieces.append(
        _composed_fill('.ridge-fill',
                       settings.get('ridge-fill-color'),
                       settings.get('ridge-fill-opacity'))
    )

    return ''.join(p for p in pieces if p)


def _is_color_value(value: str) -> bool:
    """Loose check — accept '#hex' and rgb()/rgba() strings. Used to
    avoid emitting opacity/width keys as colour vars by mistake."""
    if not isinstance(value, str):
        return False
    v = value.strip().lower()
    return v.startswith('#') or v.startswith('rgb')


def _composed_fill(selector: str, color_hex: str | None, opacity: str | None) -> str:
    """Build an `<selector>{fill:rgba(R,G,B,A);}` rule from a hex base
    colour + 0..1 opacity. Returns '' if neither is set, so the original
    insights.css fallback wins.
    """
    if not color_hex and not opacity:
        return ''
    base = color_hex or '#000000'
    a = opacity or '0.08'
    rgb = _hex_to_rgb(base)
    return f'{selector}{{fill:rgba({rgb[0]},{rgb[1]},{rgb[2]},{a});}}'


def _emit_css_block(settings: dict) -> str:
    """Build the customization `<link>` + `<style>` markup.

    The `<link>` always loads the bundled fonts.css so any font picked
    by the user (or the default Times) renders consistently across pages.
    The `<style>` block carries:
      * --xxx CSS variables for every non-metadata user override
      * --bg-image / --font-body / --font-heading composed from metadata
      * body::before/::after pseudo-elements for the bg image layer
        (only when there's actually a bg image to show)
      * @font-face for the user's custom font (only if uploaded AND
        used by at least one of body/heading)
    """
    # Always include the link to fonts.css when module is active. Browser
    # caches it forever after the first load, so this is essentially free.
    fonts_link = (
        '<link rel="stylesheet" '
        'href="/modules/customization/static/fonts/fonts.css">'
    )

    if not settings:
        return Markup(fonts_link + '<style id="customization-vars"></style>')

    # Direct emit: every non-metadata key becomes its own CSS variable.
    css_vars = {
        k: v for k, v in settings.items()
        if k not in _METADATA_KEYS
    }

    # Composed background image: overrides any leaked --bg-image so
    # flipping bg-type doesn't surface stale values.
    composed_bg = _compose_bg_image(settings)
    if composed_bg is not None:
        css_vars['bg-image'] = composed_bg

    # Composed fonts: only emit when the user picked a non-default.
    composed_body = _compose_font(settings, 'font-body-id')
    if composed_body is not None:
        css_vars['font-body'] = composed_body
    composed_heading = _compose_font(settings, 'font-heading-id')
    if composed_heading is not None:
        css_vars['font-heading'] = composed_heading

    # Notes font: opt-in. When 'notes-use-body-font' is 'true', mirror
    # the body font into --font-notes. Otherwise leave it unset so the
    # CSS rule's Times fallback wins (preserves the historic look).
    if settings.get('notes-use-body-font') == 'true':
        # Use the composed body family if computed, else fall back to
        # the explicit Times stack so the CSS doesn't end up resolving
        # `--font-notes: var(--font-body)` to Times via the fallback
        # chain, which would defeat the toggle for non-default body fonts.
        css_vars['font-notes'] = composed_body or "'Times New Roman', Times, serif"

    # Auto-invert text: overrides any manually-chosen text/muted colours
    # so the user can't end up with unreadable black-on-dark. Runs after
    # the explicit text-color/text-muted entries so we win.
    auto_text, auto_muted = _auto_invert_overrides(settings)
    if auto_text:
        css_vars['text-color'] = auto_text
        # Headings use var(--heading-color, ...) separately from body text,
        # so they must be inverted too — otherwise they keep the dark
        # default (#222) and vanish on a dark background.
        css_vars['heading-color'] = auto_text
    if auto_muted:
        css_vars['text-muted'] = auto_muted

    custom_face = _custom_font_face_rule(settings)

    # Inline chart overrides — survive a stale browser cache of
    # insights.css and add line-width / area-opacity / today-color
    # options that don't fit cleanly into a single CSS variable.
    chart_block = _chart_overrides(settings)

    # Mosaic emission must be considered before short-circuiting:
    # mosaic uses metadata-only keys, so a mosaic-only configuration
    # (no other CSS overrides) still needs to inject scripts.
    mosaic_chunks = ''
    if (settings.get('mosaic-enabled') == 'true'
            and settings.get('mosaic-filled-filename')):
        mosaic_chunks = _mosaic_script_tags(settings)

    if (not css_vars and not custom_face
            and not mosaic_chunks and not chart_block):
        return Markup(fonts_link + '<style id="customization-vars"></style>')

    parts = []
    if css_vars:
        parts.append(
            ':root {\n' + '\n'.join(f'  --{k}: {v};' for k, v in css_vars.items()) + '\n}'
        )

    # Emit the bg-image render layer unconditionally.
    #
    # Used to be gated on `composed_bg is not None` (i.e. the user had
    # already saved a gradient / image). That blocked the customization
    # page's live preview: switching bg-type to gradient or image with
    # the picker would update --bg-image via JS, but the body::before
    # pseudo-element wouldn't exist yet, so the change wasn't visible
    # until after Save + reload. Emitting it for everyone is essentially
    # free — when --bg-image resolves to `none`, the pseudo-element is
    # invisible (no image to paint).
    parts.append(
        'body { position: relative; }\n'
        'body::before {'
        '\n  content: "";'
        '\n  position: fixed;'
        '\n  inset: 0;'
        '\n  z-index: -2;'
        '\n  pointer-events: none;'
        '\n  background-image: var(--bg-image, none);'
        '\n  background-size: var(--bg-size, cover);'
        '\n  background-position: var(--bg-position, center);'
        '\n  background-repeat: var(--bg-repeat, no-repeat);'
        '\n  filter: blur(var(--bg-image-blur, 0px));'
        '\n  opacity: var(--bg-image-opacity, 1);'
        '\n}'
    )


    if custom_face:
        parts.append(custom_face)

    if chart_block:
        parts.append(chart_block)

    body = '\n'.join(parts)
    style_block = f'<style id="customization-vars">\n{body}\n</style>'

    return Markup(fonts_link + style_block + mosaic_chunks)


def _mosaic_script_tags(settings: dict) -> str:
    """Return the inline `<script>` config + a `<script src=...>` loader.

    Config shape (read by mosaic.js as `window.__CZ_MOSAIC__`):
        filledUrl     — url() of the filled image
        emptyMode     — 'color' | 'gradient' | 'image'
        emptyValue    — color hex, linear-gradient(...) string, or url()
    The loader is `defer` so it doesn't block initial render.
    """
    import json as _json
    filled = settings['mosaic-filled-filename']
    config = {
        'filledUrl': f'/customization/uploads/{filled}',
    }
    mode = settings.get('mosaic-empty-mode', 'color')
    if mode == 'image' and settings.get('mosaic-empty-filename'):
        config['emptyMode'] = 'image'
        config['emptyValue'] = (
            f'url("/customization/uploads/{settings["mosaic-empty-filename"]}")'
        )
    elif mode == 'gradient':
        a = settings.get('mosaic-empty-grad-from', '#ffffff')
        b = settings.get('mosaic-empty-grad-to',   '#dddddd')
        ang = settings.get('mosaic-empty-grad-angle', '180deg')
        config['emptyMode'] = 'gradient'
        config['emptyValue'] = f'linear-gradient({ang}, {a}, {b})'
    else:
        config['emptyMode'] = 'color'
        config['emptyValue'] = settings.get('mosaic-empty-color', '#ffffff')

    payload = _json.dumps(config, ensure_ascii=False)
    return (
        f'<script id="cz-mosaic-config">window.__CZ_MOSAIC__={payload};</script>'
        '<script defer '
        'src="/modules/customization/static/js/mosaic.js"></script>'
    )


def register_context_processor(app):
    @app.context_processor
    def inject_customization():
        return {'customization_css': _emit_css_block(_load_user_settings())}
