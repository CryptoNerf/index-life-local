"""Schema + UI defaults for customization keys.

This module declares two things:

* the **set of allowed keys** — `DEFAULTS` is the authoritative list
  of customization variables the user can override. Unknown keys are
  rejected by the API and stripped by the context processor.

* **UI initial values** — values shown in the settings page color
  pickers when no user override exists. These are *hex approximations*
  of the production fallback values baked into the existing CSS rules.

The context processor now emits ONLY user-changed values (not the
defaults). Unchanged keys stay implicit and resolve to whatever
fallback the CSS rule supplies via `var(--name, default-here)`. This
guarantees activating the module without changing anything produces
an identical-looking page.

Adding a new themable surface:
  1) add a key here with a hex picker default
  2) update the relevant CSS rule to use `var(--key, original-value)`
  3) expose the control on the settings page (template + UI handler)
"""

# Defaults are derived from the existing static/css/calendar.css and friends.
# Changing a default here changes the look of an inactive-module install,
# which is almost never what we want — be careful.
DEFAULTS = {
    # ── Page background ─────────────────────────────────────
    # bg-type selects which form of background to render:
    #   'color'    — solid colour (uses --bg-color)
    #   'gradient' — linear gradient (uses --bg-image set to linear-gradient())
    #   'image'    — uploaded image (uses --bg-image set to url())
    # The actual CSS variable that drives rendering is `--bg-image`.
    # `bg-type` is metadata so the settings UI can reconstruct the form.
    'bg-type':     'color',
    'bg-color':    '#ffffff',
    'bg-image':    'none',          # CSS background-image value, or 'none'
    'bg-size':     'cover',
    'bg-position': 'center',
    'bg-repeat':   'no-repeat',
    # Stored gradient settings — kept separately so user can flip
    # between 'gradient' and 'image' types without losing each one's
    # configuration.
    'bg-gradient-from':   '#ffffff',
    'bg-gradient-to':     '#dddddd',
    'bg-gradient-angle':  '180deg',
    # Gradient shape (metadata, not emitted as a raw var). 'linear' uses
    # the angle above; 'radial' ignores it and draws a circle from centre.
    'bg-gradient-shape':  'linear',  # 'linear' | 'radial'
    # Filename of the uploaded background image. The settings UI builds
    # url() from this; raw filename is stored so we can serve it directly
    # and so JSON stays inspectable.
    'bg-image-filename': '',
    'bg-image-blur':    '0px',     # CSS blur on the bg image only
    'bg-image-opacity': '1',       # 0..1 — visual strength of the image

    # ── Typography ──────────────────────────────────────────
    # font-body-id / font-heading-id are metadata: the catalog id of
    # the chosen font family. Context processor maps these to the
    # effective `--font-body` / `--font-heading` CSS variables. Special
    # ids: 'system' (system stack), 'times' (default classic look),
    # 'custom' (user-uploaded file → @font-face for "Custom" family).
    'font-body-id':       'times',
    'font-heading-id':    'times',
    # Filename of an uploaded custom font (.ttf/.otf/.woff/.woff2).
    # If set AND any *-id is 'custom', that side uses this file.
    'custom-font-filename': '',
    # Opt-in: when 'true', the body font is also applied to diary entry
    # notes (textarea / WYSIWYG / preview). Defaults to 'false' so the
    # historic Times look is preserved unless the user explicitly asks.
    'notes-use-body-font': 'false',
    'text-color':    '#000000',
    'heading-color': '#000000',

    # ── Brand / accent ──────────────────────────────────────
    # Used for the active menu link and other accent surfaces.
    # Matches the historic #009AFA used in the original CSS — keep this
    # defaulted to the original look so activating the module doesn't
    # cause a visual change until the user picks a different color.
    'brand-color': '#009afa',

    # ── Calendar cubes ──────────────────────────────────────
    # cube-today's blue (#0080ff) is intentionally a slightly different
    # shade from brand-color (#009afa) — keep them as separate variables
    # so users can theme each independently if they want.
    'cube-filled-color': '#000000',
    'cube-empty-color':  '#ffffff',
    'cube-border-color': '#000000',
    'cube-today-color':  '#0080ff',

    # ── Calendar mosaic (Stage 5) ───────────────────────────
    # When mosaic is active, each cube is treated as a tiny window into
    # one of two images stretched across the entire calendar grid:
    #   - mosaic-filled-filename: shown for FILLED days
    #   - mosaic-empty-filename:  shown for EMPTY days (optional)
    # If empty's filename is unset, empty days fall back to the cube
    # color/gradient defined separately (mosaic-empty-mode = 'color' |
    # 'gradient' | 'image').
    'mosaic-enabled':         'false',
    'mosaic-filled-filename': '',
    'mosaic-empty-mode':      'color',  # 'color' | 'gradient' | 'image'
    'mosaic-empty-filename':  '',
    'mosaic-empty-color':     '#ffffff',
    'mosaic-empty-grad-from': '#ffffff',
    'mosaic-empty-grad-to':   '#dddddd',
    'mosaic-empty-grad-angle': '180deg',

    # ── Insights charts ─────────────────────────────────────
    # Global "set everything at once" fallbacks. Used when a chart's
    # specific override (e.g. `river-line-color`) isn't set. Each chart
    # gets fine-grained controls in its own settings subsection — see
    # `chart_schema.py` for the per-chart keys.
    'chart-color':       '#000000',
    # Approximated from the original rgba(0,0,0,0.1) so the value is
    # still expressible as a #rrggbb hex string (native color pickers
    # don't support alpha). Visually very close on a white background.
    'chart-grid-color':  '#e6e6e6',

    # ── Neural map (deep_mind) ──────────────────────────────
    # All hex equivalents of the previous rgb()/rgba() values for the
    # same reason — keeps the picker UI honest.
    'neural-node-color': '#282828',
    'neural-node-active-color': '#009afa',
    'neural-edge-color': '#bfbfbf',
    'neural-glow-color': '#80c8fa',
    # Canvas backdrop on the neural map page. Matches the historic
    # `background: #fafafa` baked into neural_map.css so an unchanged
    # setting reproduces the original look.
    'neural-canvas-bg': '#fafafa',

    # ── Readability / contrast (Stage 7) ────────────────────
    # Muted/grey text colour — used for captions, hints, secondary
    # metadata in lists and forms. Pulled out of hardcoded #888/#666/#999
    # rules so changing text-color also pulls all the secondary text along.
    'text-muted': '#888888',
    # Auto-invert text against effective page background luminance.
    # When 'true', the context processor recomputes --text-color (and
    # --text-muted) to white-on-dark or black-on-light, overriding the
    # user's manual text-color pick. Useful when a dark photo background
    # would otherwise leave black text unreadable.
    'auto-invert-text': 'false',

    # ── AI psychologist chat avatar ─────────────────────────
    # The avatar bubble next to each assistant message. Renders as a
    # circle that can be a solid colour, a linear/radial gradient, or
    # a user-uploaded image — same idea as the page background.
    #
    # avatar-type selects the mode (metadata, not emitted as a raw var):
    #   'color'    — solid colour (uses --avatar-color)
    #   'gradient' — linear or radial (composed into --avatar-bg)
    #   'image'    — uploaded image (composed into --avatar-bg)
    'avatar-type':            'color',
    'avatar-color':           '#009afa',
    'avatar-gradient-from':   '#009afa',
    'avatar-gradient-to':     '#005ea0',
    'avatar-gradient-angle':  '180deg',
    'avatar-gradient-shape':  'linear',  # 'linear' | 'radial'
    'avatar-image-filename':  '',
}


# ── Per-chart customization keys ────────────────────────────
# These are added programmatically from the schema rather than typed
# out by hand, so adding a control to `chart_schema.CHARTS` is the
# only edit needed to also expose its default to the system.
from .chart_schema import CHART_DEFAULTS as _CHART_DEFAULTS  # noqa: E402
DEFAULTS.update(_CHART_DEFAULTS)


def merge_with_defaults(user_settings: dict) -> dict:
    """Return DEFAULTS overlaid with user values; unknown keys stripped.

    Stripping unknown keys keeps the CSS payload small and prevents
    polluting the page with stale variables from older module versions.
    """
    if not isinstance(user_settings, dict):
        user_settings = {}
    out = dict(DEFAULTS)
    for k, v in user_settings.items():
        if k in DEFAULTS and isinstance(v, str) and v.strip():
            out[k] = v
    return out
