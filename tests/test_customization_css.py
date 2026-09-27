"""Tests for the customization CSS composer (`context_processor`).

These are pure functions (no DB, no app context) that turn a settings
dict into the inline `<style>` block. The font cases double as a
regression guard for the bug where a custom *body* font leaked into
headings: `--font-heading` must only be emitted when the user actually
picks a non-default heading font, otherwise the CSS fallback (Times)
must win on its own.
"""
import json

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
# On by default now. It used to force black text on any light page and white
# on any dark one, overwriting the user's picks; switched on for everyone
# that would have thrown away every text colour choice. It now replaces a
# colour only when it is hard to read on the background.

def test_auto_invert_is_on_by_default_and_silent_on_the_default_page():
    """Nothing saved: white page, dark text, nothing to rescue."""
    assert cp._auto_invert_enabled({}) is True
    assert cp._auto_invert_overrides({}) == {}


def test_auto_invert_can_still_be_turned_off():
    assert cp._auto_invert_overrides(
        {'auto-invert-text': 'false', 'bg-type': 'color', 'bg-color': '#000000'}) == {}


def test_auto_invert_dark_bg_gives_light_text():
    out = cp._auto_invert_overrides({'bg-type': 'color', 'bg-color': '#000000'})
    assert out['text-color'] == '#ffffff'
    assert out['heading-color'] == '#ffffff'


def test_unset_muted_text_is_judged_by_its_darkest_fallback():
    """The stylesheets fall back to anything from #444 to #bbb for muted
    text. Judged by the #888 picker default it passed on a dark page, and
    the #555 subtitles stayed unreadable."""
    out = cp._auto_invert_overrides({'bg-type': 'color', 'bg-color': '#15161a'})
    assert out['text-muted'] == '#cccccc'


def test_a_readable_pick_on_a_dark_page_is_kept():
    out = cp._auto_invert_overrides(
        {'bg-type': 'color', 'bg-color': '#000000', 'text-color': '#ffe680'})
    assert 'text-color' not in out


def test_a_readable_pick_on_a_light_page_is_kept():
    """The old rule forced black here and threw away a navy choice."""
    out = cp._auto_invert_overrides(
        {'bg-type': 'color', 'bg-color': '#ffffff', 'text-color': '#1a2a6c'})
    assert out == {}


def test_light_text_on_a_light_page_is_rescued():
    out = cp._auto_invert_overrides(
        {'bg-type': 'color', 'bg-color': '#ffffff', 'text-color': '#eeeeee'})
    assert out['text-color'] == '#000000'


def test_auto_invert_image_bg_cannot_decide():
    # Can't sample a photo server-side → stays off.
    assert cp._auto_invert_overrides(
        {'auto-invert-text': 'true', 'bg-type': 'image',
         'bg-image-filename': 'p.jpg'}) == {}


def test_auto_invert_also_inverts_heading_color():
    # Regression: headings use var(--heading-color, ...) separately, so they
    # must be inverted too — otherwise they stay dark and vanish on a dark bg.
    out = str(cp._emit_css_block(
        {'auto-invert-text': 'true', 'bg-type': 'color', 'bg-color': '#000000'}))
    assert '--text-color: #ffffff' in out
    assert '--heading-color: #ffffff' in out


# ── background image composition ──────────────────────────────

def test_compose_bg_gradient():
    out = cp._compose_bg_image({
        'bg-type': 'gradient', 'bg-gradient-from': '#fff',
        'bg-gradient-to': '#000', 'bg-gradient-angle': '90deg'})
    assert out == 'linear-gradient(90deg, #fff, #000)'


def test_compose_bg_radial_gradient_ignores_angle():
    out = cp._compose_bg_image({
        'bg-type': 'gradient', 'bg-gradient-shape': 'radial',
        'bg-gradient-from': '#fff', 'bg-gradient-to': '#000',
        'bg-gradient-angle': '90deg',  # must be ignored
    })
    assert out == 'radial-gradient(circle, #fff, #000)'


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


# ── chat avatar composition ────────────────────────────────────

def test_compose_avatar_color_mode_returns_none():
    # In color mode the colour picker drives --avatar-color directly
    # via the CSS fallback chain; nothing should be composed.
    assert cp._compose_avatar_bg({}) is None
    assert cp._compose_avatar_bg({'avatar-type': 'color'}) is None


def test_compose_avatar_linear_gradient():
    out = cp._compose_avatar_bg({
        'avatar-type': 'gradient',
        'avatar-gradient-shape': 'linear',
        'avatar-gradient-from': '#fff',
        'avatar-gradient-to': '#000',
        'avatar-gradient-angle': '90deg',
    })
    assert out == 'linear-gradient(90deg, #fff, #000)'


def test_compose_avatar_radial_gradient_ignores_angle():
    # Radial gradients have no meaningful angle — the composer must not
    # leak it into the CSS, otherwise the value would be invalid.
    out = cp._compose_avatar_bg({
        'avatar-type': 'gradient',
        'avatar-gradient-shape': 'radial',
        'avatar-gradient-from': '#fff',
        'avatar-gradient-to': '#000',
        'avatar-gradient-angle': '90deg',
    })
    assert out == 'radial-gradient(circle, #fff, #000)'


def test_compose_avatar_image_with_filename():
    out = cp._compose_avatar_bg({
        'avatar-type': 'image', 'avatar-image-filename': 'abc.png',
    })
    assert out == 'url("/customization/uploads/abc.png") center / cover no-repeat'


def test_compose_avatar_image_without_filename_is_none():
    assert cp._compose_avatar_bg({'avatar-type': 'image'}) is None


def test_emit_block_only_writes_avatar_bg_for_gradient_or_image():
    # color mode: nothing composed
    out_color = str(cp._emit_css_block({'avatar-type': 'color'}))
    assert '--avatar-bg' not in out_color

    # gradient mode: composed value present
    out_grad = str(cp._emit_css_block({
        'avatar-type': 'gradient',
        'avatar-gradient-from': '#fff', 'avatar-gradient-to': '#000',
    }))
    assert '--avatar-bg: linear-gradient' in out_grad


def test_avatar_type_is_metadata_not_emitted_as_var():
    # The metadata keys must never leak into the :root block as raw vars.
    out = str(cp._emit_css_block({'avatar-type': 'gradient'}))
    assert '--avatar-type' not in out
    assert '--avatar-gradient-shape' not in out
    assert '--avatar-image-filename' not in out


def test_avatar_keys_are_accepted_by_the_save_whitelist():
    # Regression: the avatar UI silently saved nothing because /api/save
    # validates every incoming key against a hardcoded whitelist
    # (_VALIDATORS) and unrecognised ones are dropped. The composer
    # could compute the CSS fine, but nothing ever made it to the DB.
    # Lock the whitelist contents so the avatar feature stays wired.
    from app.modules.customization.routes import _VALIDATORS
    expected = {
        'avatar-type', 'avatar-color',
        'avatar-gradient-from', 'avatar-gradient-to',
        'avatar-gradient-angle', 'avatar-gradient-shape',
        'avatar-image-filename',
    }
    missing = expected - set(_VALIDATORS)
    assert not missing, f'avatar keys missing from save whitelist: {missing}'


def test_avatar_validators_reject_obvious_garbage():
    # Cheap sanity that the validators we wired in actually validate.
    from app.modules.customization.routes import _VALIDATORS
    assert _VALIDATORS['avatar-type']('gradient') is True
    assert _VALIDATORS['avatar-type']('nope') is False
    assert _VALIDATORS['avatar-gradient-shape']('linear') is True
    assert _VALIDATORS['avatar-gradient-shape']('weird') is False
    assert _VALIDATORS['avatar-color']('#009afa') is True
    assert _VALIDATORS['avatar-color']('not-a-color') is False
    assert _VALIDATORS['avatar-gradient-angle']('180deg') is True
    assert _VALIDATORS['avatar-gradient-angle']('180') is False


# ── Colour the day by its rating ────────────────────────────────────
# The scale needs three things to line up: the API must accept the keys,
# the context processor must emit the .cube.rN rules, and the calendar must
# put the rating on the cube. The first of those silently rejected the keys
# when the feature shipped, so the mode did nothing at all.

def test_scale_keys_are_accepted_by_the_save_api():
    from app.modules.customization import routes as cz_routes
    for key in ('cube-scale-enabled', 'cube-scale-low', 'cube-scale-mid', 'cube-scale-high'):
        assert key in cz_routes._ALLOWED_KEYS, f'{key} would be rejected by /api/save'


def test_scale_keys_belong_to_the_calendar_section():
    """So "reset this section" clears them along with the other cube colours."""
    from app.modules.customization import routes as cz_routes
    section = cz_routes._SECTION_KEYS['sec-calendar']
    assert {'cube-scale-enabled', 'cube-scale-low',
            'cube-scale-mid', 'cube-scale-high'} <= section


def test_scale_emits_nothing_while_switched_off():
    assert cp._cube_scale_rules({}) == ''
    assert cp._cube_scale_rules({'cube-scale-enabled': 'false'}) == ''


def test_scale_interpolates_between_the_three_stops():
    css = cp._cube_scale_rules({
        'cube-scale-enabled': 'true',
        'cube-scale-low': '#000000',
        'cube-scale-mid': '#808080',
        'cube-scale-high': '#ffffff',
    })
    assert css.count('.cube.filled.r') == 10
    assert '.cube.filled.r1, .cube.hovered.r1 { background: rgb(0, 0, 0); }' in css
    assert '.cube.filled.r10, .cube.hovered.r10 { background: rgb(255, 255, 255); }' in css

    # The middle stop sits at 5.5, i.e. between the two middle ratings, and
    # the ramp rises monotonically from one end to the other.
    import re
    values = [int(m) for m in re.findall(r'background: rgb\((\d+),', css)]
    assert values == sorted(values)
    assert values[4] < 128 < values[5]


# ── cards ─────────────────────────────────────────────────────
# The blocks on the charts, weather, modules and sync pages used to be
# painted with the page colour, full stop. They can now have their own.

def test_cards_emit_nothing_by_default():
    assert cp._card_rules({}, cp._page_text_colours({})) == ''
    assert 'viz-card' not in str(cp._emit_css_block({}))


def test_a_card_colour_with_opacity_becomes_rgba_on_every_card():
    css = cp._card_rules({'card-bg-mode': 'color', 'card-bg-color': '#102030',
                          'card-bg-opacity': '0.5'}, cp._page_text_colours({}))
    assert 'background:rgba(16,32,48,0.5)' in css
    for sel in ('.viz-card', '.wx-stat', '.module-card', '.mpd-entry'):
        assert 'html ' + sel in css
    assert '.step-card:not(.step-warn)' in css, 'the warning card keeps its colour'


def test_card_text_is_judged_against_the_card_not_the_page():
    """Black page, white cards: the page text turns white, the cards' must
    not — it would vanish on them."""
    settings = {'bg-type': 'color', 'bg-color': '#000000',
                'card-bg-mode': 'color', 'card-bg-color': '#ffffff'}
    out = str(cp._emit_css_block(settings))
    assert '--text-color: #ffffff' in out                  # the page
    cards = cp._card_rules(settings, dict(cp._page_text_colours(settings),
                                          **cp._auto_invert_overrides(settings)))
    assert '--text-color:#000000' in cards                  # the cards


def test_page_coloured_cards_over_a_dark_photo_keep_dark_text():
    """The bug behind the request: a dark photo turns the page text white,
    while the cards stay painted with the (white) page colour."""
    settings = {'bg-type': 'image', 'bg-image-filename': 'a' * 16 + '.jpg',
                'bg-image-avg-color': '#101010'}
    page_text = dict(cp._page_text_colours(settings), **cp._auto_invert_overrides(settings))
    assert page_text['text-color'] == '#ffffff'
    cards = cp._card_rules(settings, page_text)
    assert '--text-color:#000000' in cards
    assert '.wx-stat' not in cards, 'the see-through tiles sit on the photo, not on white'


def test_a_chosen_card_text_colour_is_used():
    cards = cp._card_rules({'card-text-color': '#7a1f1f'}, cp._page_text_colours({}))
    assert '--text-color:#7a1f1f' in cards
    assert '--heading-color:#7a1f1f' in cards


def test_a_chosen_border_colour_applies_to_every_card():
    cards = cp._card_rules({'card-border-color': '#abcdef'}, cp._page_text_colours({}))
    assert 'border-color:#abcdef' in cards and '.wx-stat' in cards


def test_card_settings_never_leak_as_css_variables():
    out = str(cp._emit_css_block({'card-bg-mode': 'color', 'card-bg-color': '#123456',
                                  'card-bg-opacity': '0.4'}))
    assert '--card-bg' not in out


# ── symbols in day cells ──────────────────────────────────────

from app.modules.customization import cube_symbols as cs  # noqa: E402
import re  # noqa: E402


def _sym_colour(css, rating):
    """The symbol colour the rules give a filled cell of this rating."""
    m = re.search(r'\.cube\.filled\.r%d \.cube-sym[^{]*\{color:(#[0-9a-f]{6});\}' % rating, css)
    assert m, 'no symbol colour for r%d' % rating
    return m.group(1)


def test_symbols_are_off_by_default():
    assert cs.for_template({}) is None
    assert cs.css_rules({}) == ''


def test_symbols_default_to_the_ratings_themselves():
    assert cs.for_template({'cube-symbols-enabled': 'true'}) == {
        i: str(i) for i in range(1, 11)}


def test_an_empty_symbol_means_no_symbol_for_that_rating():
    faces = ['😭', '😢', '', '', '😐', '', '', '', '😄', '🤩']
    got = cs.for_template({'cube-symbols-enabled': 'true',
                           'cube-symbols': json.dumps(faces, ensure_ascii=False)})
    assert got == {1: '😭', 2: '😢', 5: '😐', 9: '😄', 10: '🤩'}


@pytest.mark.parametrize('value', [
    '["1","2"]',                                   # not ten
    'not json',
    json.dumps(['x' * 9] + [''] * 9),              # too long
    json.dumps(['a\u0000'] + [''] * 9),           # control character
    json.dumps([1] + [''] * 9),                    # not a string
])
def test_bad_symbol_lists_are_rejected(value):
    assert cs.is_valid(value) is False


def test_emoji_with_joiners_and_skin_tones_are_accepted():
    assert cs.is_valid(json.dumps(['👍🏽', '❤️', '👩‍💻'] + [''] * 7, ensure_ascii=False))


def test_the_symbol_colour_reads_on_what_the_cell_is_painted_with():
    dark = cs.css_rules({'cube-symbols-enabled': 'true'})           # black fill
    assert _sym_colour(dark, 7) == '#ffffff'
    light = cs.css_rules({'cube-symbols-enabled': 'true', 'cube-filled-color': '#f5f5dc'})
    assert _sym_colour(light, 7) == '#000000'
    unfilled = cs.css_rules({'cube-symbols-enabled': 'true',
                             'cube-symbols-hide-fill': 'true'})   # white empty colour
    assert _sym_colour(unfilled, 7) == '#000000'
    assert 'background:var(--cube-empty-color' in unfilled


def test_symbol_colours_follow_the_rating_scale():
    css = cs.css_rules({'cube-symbols-enabled': 'true', 'cube-scale-enabled': 'true',
                        'cube-scale-low': '#000000', 'cube-scale-high': '#ffffff',
                        'cube-scale-mid': '#808080'})
    assert _sym_colour(css, 1) == '#ffffff'
    assert _sym_colour(css, 10) == '#000000'


def test_the_symbol_list_never_becomes_a_css_variable():
    out = str(cp._emit_css_block({'cube-symbols-enabled': 'true',
                                  'cube-symbols': json.dumps(['<'] + [''] * 9)}))
    assert '--cube-symbols' not in out


# ── the day page's rating row ─────────────────────────────────
# It used to fill every chosen cube black whatever the calendar did. It now
# uses the calendar's own classes, so these rules have to cover it.

def test_the_hover_preview_takes_the_rating_colour_too():
    css = cp._cube_scale_rules({'cube-scale-enabled': 'true'})
    assert '.cube.hovered.r7' in css


def test_unchosen_symbols_in_the_rating_row_are_dimmed():
    css = cs.css_rules({'cube-symbols-enabled': 'true'})
    assert '.cubes-row .cube.has-sym:not(.filled):not(.hovered) .cube-sym{opacity:.35;}' in css


def test_a_symbol_on_an_unfilled_cube_reads_on_the_empty_colour():
    css = cs.css_rules({'cube-symbols-enabled': 'true', 'cube-empty-color': '#111111'})
    assert 'html .cube.has-sym .cube-sym{color:#ffffff;}' in css


# ── cards the first pass missed ───────────────────────────────

def test_colour_mode_reaches_the_sync_status_box_and_the_neural_panel():
    css = cp._card_rules({'card-bg-mode': 'color', 'card-bg-color': '#202020'},
                         cp._page_text_colours({}))
    assert 'html .status-card' in css and 'html .detail-panel' in css


def test_every_card_gets_its_text_in_colour_mode():
    """The neural panel pins dark text of its own; a dark card colour must
    replace it, not leave it black on black."""
    css = cp._card_rules({'card-bg-mode': 'color', 'card-bg-color': '#202020'},
                         cp._page_text_colours({}))
    rule = [r for r in css.split('\n') if '--text-color' in r][0]
    assert '.detail-panel' in rule and '--text-color:#ffffff' in rule


# ── silhouettes ───────────────────────────────────────────────

def test_silhouettes_invert_on_a_dark_page_but_not_on_their_chips():
    css = cp._silhouette_rules({'bg-type': 'color', 'bg-color': '#101010'})
    assert 'html img[src*="/silhouettes/"]{filter:invert(1);}' in css
    assert 'html .mp-sil-opt img[src*="/silhouettes/"]' in css      # picker chips stay black
    assert '{filter:none;}' in css


def test_silhouettes_are_left_alone_on_a_light_page():
    assert cp._silhouette_rules({}) == ''


def test_silhouettes_on_a_light_card_over_a_dark_page_stay_black():
    css = cp._silhouette_rules({'bg-type': 'color', 'bg-color': '#101010',
                                'card-bg-mode': 'color', 'card-bg-color': '#f3efe6'})
    assert 'html .viz-card img[src*="/silhouettes/"]{filter:none;}' in css


def test_silhouettes_follow_the_readability_switch():
    assert cp._silhouette_rules({'bg-type': 'color', 'bg-color': '#101010',
                                 'auto-invert-text': 'false'}) == ''


# ── neural map labels ─────────────────────────────────────────
# The map draws on its own background (near-white by default) but took the
# page's text colour for its labels: a black page turned them white, on a
# white canvas.

def test_a_dark_page_does_not_whiten_the_labels_on_a_light_canvas():
    css = cp._neural_canvas_rules({'bg-type': 'color', 'bg-color': '#000000'},
                                  dict(cp._page_text_colours({}), **cp._auto_invert_overrides(
                                      {'bg-type': 'color', 'bg-color': '#000000'})))
    assert css.startswith('html #graph-container{')
    assert '--text-color:#000000' in css


def test_a_dark_canvas_on_a_light_page_gets_light_labels():
    settings = {'neural-canvas-bg': '#101010'}
    css = cp._neural_canvas_rules(settings, cp._page_text_colours(settings))
    assert '--text-color:#ffffff' in css


def test_the_default_page_and_canvas_need_nothing():
    assert cp._neural_canvas_rules({}, cp._page_text_colours({})) == ''


def test_the_emitted_block_carries_the_map_rule():
    out = str(cp._emit_css_block({'bg-type': 'color', 'bg-color': '#000000'}))
    assert 'html #graph-container{--text-color:#000000' in out
