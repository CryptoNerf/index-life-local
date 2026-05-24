"""Tests for the customization CSS composer (`context_processor`).

These are pure functions (no DB, no app context) that turn a settings
dict into the inline `<style>` block. The font cases double as a
regression guard for the bug where a custom *body* font leaked into
headings: `--font-heading` must only be emitted when the user actually
picks a non-default heading font, otherwise the CSS fallback (Times)
must win on its own.
"""
import pytest

from app.modules.customization import context_processor as cp


# ── colour parsing ────────────────────────────────────────────

@pytest.mark.parametrize('value,expected', [
    ('#fff', (255, 255, 255)),
    ('#000000', (0, 0, 0)),
    ('#ff8800', (255, 136, 0)),
    ('abc', (170, 187, 204)),          # leading '#' optional
    ('garbage', (0, 0, 0)),            # never raises
    ('#12', (0, 0, 0)),                # wrong length
])
def test_hex_to_rgb(value, expected):
    assert cp._hex_to_rgb(value) == expected


@pytest.mark.parametrize('value,expected', [
    ('#abc', (170, 187, 204, 1.0)),
    ('rgb(1, 2, 3)', (1, 2, 3, 1.0)),
    ('rgba(1, 2, 3, 0.5)', (1, 2, 3, 0.5)),
    ('transparent', None),
    ('', None),
    ('not-a-color', None),
])
def test_parse_css_color(value, expected):
    assert cp._parse_css_color(value) == expected


def test_luma_black_and_white():
    assert cp._luma((0, 0, 0)) == 0
    assert cp._luma((255, 255, 255)) == pytest.approx(255.0)


# ── auto-invert text colour ───────────────────────────────────

def test_auto_invert_off_returns_nothing():
    assert cp._auto_invert_overrides({}) == (None, None)


def test_auto_invert_dark_bg_gives_light_text():
    text, muted = cp._auto_invert_overrides(
        {'auto-invert-text': 'true', 'bg-type': 'color', 'bg-color': '#000000'})
    assert text == '#ffffff'
    assert muted == '#cccccc'


def test_auto_invert_light_bg_gives_dark_text():
    text, muted = cp._auto_invert_overrides(
        {'auto-invert-text': 'true', 'bg-type': 'color', 'bg-color': '#ffffff'})
    assert text == '#000000'
    assert muted == '#666666'


def test_auto_invert_image_bg_cannot_decide():
    # Can't sample a photo server-side → stays off.
    assert cp._auto_invert_overrides(
        {'auto-invert-text': 'true', 'bg-type': 'image',
         'bg-image-filename': 'p.jpg'}) == (None, None)


# ── background image composition ──────────────────────────────

def test_compose_bg_gradient():
    out = cp._compose_bg_image({
        'bg-type': 'gradient', 'bg-gradient-from': '#fff',
        'bg-gradient-to': '#000', 'bg-gradient-angle': '90deg'})
    assert out == 'linear-gradient(90deg, #fff, #000)'


def test_compose_bg_image_url():
    out = cp._compose_bg_image({'bg-type': 'image', 'bg-image-filename': 'p.jpg'})
    assert out == 'url("/customization/uploads/p.jpg")'


def test_compose_bg_image_without_filename_is_none():
    assert cp._compose_bg_image({'bg-type': 'image'}) is None


def test_compose_bg_solid_colour_is_none():
    assert cp._compose_bg_image({'bg-type': 'color'}) is None
    assert cp._compose_bg_image({}) is None


# ── composed rgba fills ───────────────────────────────────────

def test_composed_fill_builds_rgba():
    assert cp._composed_fill('.x', '#ff0000', '0.5') == '.x{fill:rgba(255,0,0,0.5);}'


def test_composed_fill_defaults_colour_when_only_opacity():
    assert cp._composed_fill('.x', None, '0.3') == '.x{fill:rgba(0,0,0,0.3);}'


def test_composed_fill_empty_when_nothing_set():
    assert cp._composed_fill('.x', None, None) == ''


# ── font composition ──────────────────────────────────────────

def test_compose_font_default_times_emits_nothing():
    # 'times' (and unset) must return None so the CSS Times fallback wins.
    assert cp._compose_font({'font-body-id': 'times'}, 'font-body-id') is None
    assert cp._compose_font({}, 'font-body-id') is None


def test_compose_font_bundled_id_resolves_family():
    fam = cp._compose_font({'font-body-id': 'inter'}, 'font-body-id')
    assert fam and 'Inter' in fam


def test_compose_font_custom_requires_uploaded_file():
    assert cp._compose_font({'font-body-id': 'custom'}, 'font-body-id') is None
    fam = cp._compose_font(
        {'font-body-id': 'custom', 'custom-font-filename': 'my.woff2'},
        'font-body-id')
    assert fam == "'Custom', sans-serif"


# ── end-to-end <style> block (the font-leak regression) ───────

def test_empty_settings_emit_no_font_vars():
    out = str(cp._emit_css_block({}))
    assert '--font-body' not in out
    assert '--font-heading' not in out


def test_custom_body_font_does_not_leak_into_heading():
    # The core regression: pick a non-default BODY font; HEADING must stay
    # unset so it falls back to Times rather than inheriting the body font.
    out = str(cp._emit_css_block({'font-body-id': 'inter'}))
    assert '--font-body:' in out
    assert '--font-heading' not in out


def test_custom_heading_font_emits_only_heading():
    out = str(cp._emit_css_block({'font-heading-id': 'inter'}))
    assert '--font-heading:' in out
    assert '--font-body' not in out


def test_uploaded_custom_font_emits_face_and_var():
    out = str(cp._emit_css_block(
        {'font-body-id': 'custom', 'custom-font-filename': 'my.woff2'}))
    assert '@font-face' in out
    assert 'my.woff2' in out
    assert "--font-body: 'Custom'" in out


def test_custom_font_without_upload_emits_neither():
    out = str(cp._emit_css_block({'font-body-id': 'custom'}))
    assert '@font-face' not in out
    assert '--font-body' not in out
