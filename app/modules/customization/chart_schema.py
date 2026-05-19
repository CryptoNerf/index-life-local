"""Per-chart customization schema.

Defines what each chart in the insights module is themable for. The
schema drives:

  * `defaults.py` → adds every key with its default value
  * `routes.py`   → registers validators per key type + per-chart
                    reset sections (`sec-chart-river`, etc.)
  * `context_processor.py` → emits inline override CSS rules so the
                    detail page reflects user choices, cache-proof
  * `settings.html` → renders one subsection per chart by looping
                    over CHARTS (lots of duplication avoided)
  * `settings.js` → renders the matching mini-preview using each
                    chart's `preview_id`

Adding a new themable surface to an existing chart:
  1) add a control row to that chart's `controls` list
  2) update the inline-emitter mapping in context_processor
     (`_chart_selector_for_key`) to know which CSS selector(s)
     receive the new property
  3) update the JS preview if it should reflect the new control

Adding a new chart:
  1) add a CHARTS entry with its controls + preview_id
  2) write the JS mini-preview render function in settings.js
  3) add inline-emitter mappings for its keys in context_processor

Why per-chart instead of one global `chart-color`:
  * Different charts have visually different "primary" colour ranges
    (e.g. river is a single line; rhythm is a heatmap with opacity-
    encoded data; rose is petals with refs). One global value can't
    do justice to all of them.
  * Per-chart preview lets the user *see* the effect before saving.

The global `chart-color` / `chart-grid-color` settings (defined
elsewhere in defaults.py) act as "set everything blue at once"
fallbacks. Per-chart keys override them when set.
"""

# Each control is rendered as a row in the chart's subsection.
# Type → matching validator + UI widget:
#   color  → color picker + hex input
#   slider → range input + value label; needs `unit` and `min/max/step`
#   unit   → 0..1 percentage slider
CHARTS = [
    {
        'id': 'overview',
        'label': 'Overview heatmap',
        'description': (
            'Year heatmap of daily ratings; the landing-page summary view.'
        ),
        'preview_id': 'preview-chart-overview',
        'controls': [
            {'key': 'overview-heat-color',  'type': 'color', 'label': 'Cell color',          'default': '#000000'},
            {'key': 'overview-empty-color', 'type': 'color', 'label': 'Empty cell color',    'default': '#ffffff'},
            {'key': 'overview-bar-color',   'type': 'color', 'label': 'Bar color (sidebar)', 'default': '#000000'},
            {'key': 'overview-today-color', 'type': 'color', 'label': 'Today highlight',     'default': '#009afa'},
        ],
    },
    {
        'id': 'spiral',
        'label': 'Spiral year',
        'description': (
            'Each day a dot on an unwinding spiral. Concentric guide '
            'rings, month markers, and a today highlight.'
        ),
        'preview_id': 'preview-chart-spiral',
        'controls': [
            {'key': 'spiral-dot-color',    'type': 'color', 'label': 'Day dot color',  'default': '#000000'},
            {'key': 'spiral-guide-color',  'type': 'color', 'label': 'Guide rings',    'default': '#d8d8d8'},
            {'key': 'spiral-today-color', 'type': 'color', 'label': 'Today ring',      'default': '#009afa'},
            {'key': 'spiral-month-color',  'type': 'color', 'label': 'Month markers',  'default': '#666666'},
        ],
    },
    {
        'id': 'rose',
        'label': 'Rose (weekday)',
        'description': (
            'Seven petals, one per weekday — shape shows that '
            'weekday\'s rating distribution; darkness shows its average.'
        ),
        'preview_id': 'preview-chart-rose',
        'controls': [
            {'key': 'rose-petal-color', 'type': 'color', 'label': 'Petal color',           'default': '#000000'},
            {'key': 'rose-empty-color', 'type': 'color', 'label': 'Empty petal color',     'default': '#eaeaea'},
            {'key': 'rose-ref-color',   'type': 'color', 'label': 'Reference circles',     'default': '#d8d8d8'},
        ],
    },
    {
        'id': 'ridgeline',
        'label': 'Ridgeline (monthly distributions)',
        'description': (
            'Twelve stacked ridges, one per month — shape reveals each '
            'month\'s rating distribution.'
        ),
        'preview_id': 'preview-chart-ridgeline',
        'controls': [
            {'key': 'ridge-fill-color',     'type': 'color',  'label': 'Ridge fill color',  'default': '#000000'},
            {'key': 'ridge-fill-opacity',   'type': 'unit',   'label': 'Ridge fill opacity','default': '0.20'},
            {'key': 'ridge-line-color',     'type': 'color',  'label': 'Ridge outline',     'default': '#000000'},
            {'key': 'ridge-baseline-color', 'type': 'color',  'label': 'Baseline (zero)',   'default': '#888888'},
        ],
    },
    {
        'id': 'rhythm',
        'label': 'Rhythm (weekday × month)',
        'description': (
            'Heatmap with weekday rows and month columns. Cell darkness '
            'encodes average rating for that combination.'
        ),
        'preview_id': 'preview-chart-rhythm',
        'controls': [
            {'key': 'rhythm-cell-color',    'type': 'color', 'label': 'Cell color (data)',     'default': '#000000'},
            {'key': 'rhythm-empty-color',   'type': 'color', 'label': 'Empty cell color',      'default': '#f0f0f0'},
            {'key': 'rhythm-weekend-color', 'type': 'color', 'label': 'Weekend separator',     'default': '#cccccc'},
        ],
    },
    {
        'id': 'activities-zoom',
        'label': 'Activities zoom',
        'description': (
            'Packed circles — bigger = more mentions; outer shade = '
            'mood vs your average; inner shade = that day\'s rating.'
        ),
        'preview_id': 'preview-chart-activities-zoom',
        'controls': [
            {'key': 'az-circle-color',  'type': 'color', 'label': 'Circle color',       'default': '#000000'},
            {'key': 'az-circle-stroke', 'type': 'color', 'label': 'Circle stroke',      'default': '#4d4d4d'},
            {'key': 'az-canvas-bg',     'type': 'color', 'label': 'Canvas background',  'default': '#fafafa'},
            {'key': 'az-label-color',   'type': 'color', 'label': 'Label color',        'default': '#ffffff'},
        ],
    },
    {
        'id': 'river',
        'label': 'River of mood',
        'description': (
            'Smoothed line crossing the year, raw daily dots, soft area '
            'fill underneath, and a vertical "today" marker.'
        ),
        'preview_id': 'preview-chart-river',
        'controls': [
            {'key': 'river-line-color',    'type': 'color',  'label': 'Line color',         'default': '#000000'},
            {'key': 'river-line-width',    'type': 'slider', 'unit': 'px',       'min': 1, 'max': 4, 'step': 0.2, 'label': 'Line width',         'default': '1.6px'},
            {'key': 'river-area-color',    'type': 'color',  'label': 'Area fill color',    'default': '#000000'},
            {'key': 'river-area-opacity',  'type': 'unit',   'label': 'Area fill opacity',  'default': '0.08'},
            {'key': 'river-dot-color',     'type': 'color',  'label': 'Raw daily dot color','default': '#000000'},
            {'key': 'river-today-color',   'type': 'color',  'label': 'Today marker',       'default': '#009afa'},
            {'key': 'river-grid-color',    'type': 'color',  'label': 'Gridlines',          'default': '#c8c8c8'},
        ],
    },
]


# Convenience: flat dict {key → control}. Useful for validator lookup.
ALL_CONTROLS = {
    ctrl['key']: ctrl
    for chart in CHARTS
    for ctrl in chart['controls']
}


# Convenience: defaults flat dict. Used by defaults.DEFAULTS.update().
CHART_DEFAULTS = {
    ctrl['key']: ctrl['default']
    for ctrl in ALL_CONTROLS.values()
}


# Convenience: per-chart key set. Used by routes._SECTION_KEYS for the
# per-section reset endpoint. Section ids match `sec-chart-<id>`.
CHART_SECTION_KEYS = {
    f'sec-chart-{chart["id"]}': {ctrl['key'] for ctrl in chart['controls']}
    for chart in CHARTS
}
