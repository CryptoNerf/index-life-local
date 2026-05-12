"""Bundled font catalog.

Each entry has:
  id      — short identifier used in saved settings (`font-body-id` etc.)
  label   — human-readable name shown in the settings dropdown
  family  — full CSS `font-family` value with appropriate fallback stack

Special ids:
  'system' — generic system stack, always available without bundled files
  'times'  — Times New Roman, the historic default look of the app
  'custom' — placeholder; actual family is "Custom" rendered from the
             user-uploaded file in `custom-font-filename`

The 8 bundled fonts (Inter / Roboto / Lora / Playfair Display /
JetBrains Mono / Caveat / Manrope / Merriweather) are loaded by
`static/fonts/fonts.css`, generated alongside the woff2 files. To add
a new bundled font: drop the woff2 in static/fonts/, add it to fonts.css,
and add an entry below.
"""

FONT_CATALOG = [
    {
        'id': 'system',
        'label': 'System default',
        'family': "system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif",
        'sample': 'The quick brown fox jumps over the lazy dog. Шустрая лиса.',
    },
    {
        'id': 'times',
        'label': 'Times (classic)',
        'family': "'Times New Roman', Times, serif",
        'sample': 'The quick brown fox jumps over the lazy dog. Шустрая лиса.',
    },
    {
        'id': 'inter',
        'label': 'Inter',
        'family': "'Inter', sans-serif",
        'sample': 'The quick brown fox jumps over the lazy dog. Шустрая лиса.',
    },
    {
        'id': 'roboto',
        'label': 'Roboto',
        'family': "'Roboto', sans-serif",
        'sample': 'The quick brown fox jumps over the lazy dog. Шустрая лиса.',
    },
    {
        'id': 'manrope',
        'label': 'Manrope',
        'family': "'Manrope', sans-serif",
        'sample': 'The quick brown fox jumps over the lazy dog. Шустрая лиса.',
    },
    {
        'id': 'lora',
        'label': 'Lora',
        'family': "'Lora', serif",
        'sample': 'The quick brown fox jumps over the lazy dog. Шустрая лиса.',
    },
    {
        'id': 'merriweather',
        'label': 'Merriweather',
        'family': "'Merriweather', serif",
        'sample': 'The quick brown fox jumps over the lazy dog. Шустрая лиса.',
    },
    {
        'id': 'playfair',
        'label': 'Playfair Display',
        'family': "'Playfair Display', serif",
        'sample': 'The quick brown fox jumps over the lazy dog. Шустрая лиса.',
    },
    {
        'id': 'jetbrains-mono',
        'label': 'JetBrains Mono',
        'family': "'JetBrains Mono', ui-monospace, 'Menlo', monospace",
        'sample': 'The quick brown fox jumps over the lazy dog. Шустрая лиса.',
    },
    {
        'id': 'caveat',
        'label': 'Caveat (handwritten)',
        'family': "'Caveat', cursive",
        'sample': 'The quick brown fox jumps over the lazy dog. Шустрая лиса.',
    },
    {
        'id': 'custom',
        'label': 'Custom (uploaded)',
        'family': "'Custom', sans-serif",
        'sample': 'The quick brown fox jumps over the lazy dog. Шустрая лиса.',
    },
]

CATALOG_BY_ID = {entry['id']: entry for entry in FONT_CATALOG}

VALID_FONT_IDS = set(CATALOG_BY_ID.keys())


def family_for_id(font_id: str) -> str | None:
    """Return the CSS font-family stack for a catalog id, or None if unknown."""
    entry = CATALOG_BY_ID.get(font_id)
    return entry['family'] if entry else None
