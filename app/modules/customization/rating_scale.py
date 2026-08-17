# index.life — Local mood diary
# https://github.com/CryptoNerf/index-life-local
# Copyright (C) 2026 Émile Alexanyan
#
# Licensed under AGPL-3.0 with additional terms per Section 7
# (preservation of author attribution, no misrepresentation of
# origin). See LICENSE and COPYRIGHT at the root of this project.
"""The rating → colour scale, in one place.

Turning on "colour the day by its rating" paints the calendar grid from a
three-stop scale (1 → 5.5 → 10). The charts that draw days — the year
heatmap, the spiral, the rose, the rhythm grid, the river's daily dots —
should then speak the same colour language: a seven in the calendar and a
seven on the spiral are the same green, or the grid and the charts are two
different claims about the same day.

But the charts are also themable one by one on the customization page, and a
colour the user picked on purpose outranks a default that follows the grid.
So `ChartScale.color()` answers `None` for a chart whose own colour the user
has set — the template then falls back to its existing single-colour-plus-
opacity rendering, untouched.

Only keys the user actually saved reach here (see
`context_processor._load_user_settings`), which is what makes "has the user
chosen a colour for this chart?" answerable at all.
"""

# Which key counts as "the user picked this chart's day colour". Each is the
# surface that draws a day: heat cells, spiral dots, rose petals, rhythm
# cells, the river's raw daily dots. A chart's other keys (guides, today
# markers, gridlines) say nothing about how a day should be painted.
CHART_DAY_KEY = {
    'overview': 'overview-heat-color',
    'spiral':   'spiral-dot-color',
    'rose':     'rose-petal-color',
    'rhythm':   'rhythm-cell-color',
    'river':    'river-dot-color',
}

# "Make every chart this colour at once" — a deliberate choice about charts
# just as much as a per-chart one, so it also outranks following the grid.
GLOBAL_CHART_KEY = 'chart-color'

_DEFAULT_STOPS = ('#c0392b', '#e0c14a', '#2a8f2a')


def hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    """Parse `#rrggbb` (or `#rgb`) → (r, g, b). Black on bad input."""
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


def _mix(a, b, k):
    """Linear blend between two (r, g, b) tuples, k in 0..1."""
    return tuple(round(a[i] + (b[i] - a[i]) * k) for i in range(3))


def stops(settings: dict) -> tuple:
    """The three scale stops as rgb triples: rating 1, 5.5 and 10."""
    from .defaults import DEFAULTS
    out = []
    for key, fallback in zip(('cube-scale-low', 'cube-scale-mid',
                              'cube-scale-high'), _DEFAULT_STOPS):
        out.append(hex_to_rgb(settings.get(key) or DEFAULTS.get(key, fallback)))
    return tuple(out)


def rgb_at(scale_stops, rating) -> tuple[int, int, int]:
    """Colour for a rating on the 1..10 scale.

    Ratings need not be whole: the rose and the rhythm grid paint averages,
    and an average of 6.4 sits properly between the sixes and the sevens
    rather than being rounded onto one of them.
    """
    low, mid, high = scale_stops
    pos = (float(rating) - 1) / 9
    pos = max(0.0, min(1.0, pos))
    if pos <= 0.5:
        return _mix(low, mid, pos * 2)
    return _mix(mid, high, (pos - 0.5) * 2)


def is_enabled(settings: dict) -> bool:
    return settings.get('cube-scale-enabled') == 'true'


class ChartScale:
    """Handed to templates as `cz_rating_scale` while the mode is on.

    Absent entirely when the grid is not coloured by rating (or the
    customization module is off), so a template's `if cz_rating_scale`
    guard is the whole story.
    """

    def __init__(self, settings: dict):
        self._stops = stops(settings)
        chosen = set(settings)
        self._overridden = {
            chart for chart, key in CHART_DAY_KEY.items()
            if key in chosen or GLOBAL_CHART_KEY in chosen
        }

    def follows_grid(self, chart: str) -> bool:
        """True while this chart still takes its day colour from the grid."""
        return chart in CHART_DAY_KEY and chart not in self._overridden

    def color(self, chart: str, rating) -> str | None:
        """`rgb(r, g, b)` for this day, or None to leave the chart alone."""
        if rating is None or not self.follows_grid(chart):
            return None
        return 'rgb(%d, %d, %d)' % rgb_at(self._stops, rating)

    def color_across(self, chart: str, position) -> str | None:
        """A colour from the same palette, placed by fraction instead of rating.

        For a chart whose marks are compared against each other rather than
        against the 1–10 scale. The rose is the case: seven weekday averages
        usually sit within half a point, so reading them off the absolute
        scale paints seven petals the same yellow and the weekday differences
        — the only thing the chart is about — disappear. Spreading the same
        red-to-green palette across the span it actually covers keeps the
        calendar's colours and the comparison both.
        """
        if position is None or not self.follows_grid(chart):
            return None
        return self.color(chart, 1 + max(0.0, min(1.0, float(position))) * 9)

    def legend(self, chart: str, steps: int = 5) -> list:
        """Evenly spaced colours from 1 to 10, for a chart's legend.

        The legends read low → high, and they have to be recoloured with the
        marks: a row of grey swatches next to red-to-green days would be
        describing a chart that is no longer on the page.
        """
        if not self.follows_grid(chart):
            return []
        return [self.color(chart, 1 + i * 9 / (steps - 1)) for i in range(steps)]


def for_charts(settings: dict):
    """A ChartScale while the mode is on, otherwise None."""
    return ChartScale(settings) if is_enabled(settings) else None
