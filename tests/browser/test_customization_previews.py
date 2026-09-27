"""Every preview on the customization page, driven in a real browser.

The previews are JavaScript mirrors of what the server renders, and they
drifted: the calendar preview ignored "colour the day by its rating", the
chart previews ignored the scale altogether, the accent colour and fonts
never reached the charts, the frames were a fixed near-white, and the
neural map drew its labels in the page's text colour on its own light
canvas. These tests change each control the way a user does (typing in a
picker, in its hex field, toggling, clicking a preset) and compare what the
preview draws with what it should draw — and, after saving, with the real
pages.

Opt-in, because they need Chrome: INDEXLIFE_BROWSER_TESTS=1 pytest tests/browser
"""
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

import pytest

from ._cdp import Browser, chrome_path

pytestmark = pytest.mark.skipif(
    not os.environ.get('INDEXLIFE_BROWSER_TESTS') or not chrome_path(),
    reason='browser tests are opt-in: set INDEXLIFE_BROWSER_TESTS=1 (needs Chrome)')

ROOT = Path(__file__).resolve().parents[2]

HELPERS = r"""
window.T = {
  color(id, hex) { const el = document.getElementById(id); el.value = hex;
    el.dispatchEvent(new Event('input', {bubbles: true})); },
  colorKey(key, hex) { T.color(document.querySelector('[data-key="' + key + '"]').id, hex); },
  hex(pickerId, hex) { const el = document.querySelector('input[data-hex-for="' + pickerId + '"]');
    el.value = hex; el.dispatchEvent(new Event('input', {bubbles: true})); },
  toggle(id, on) { const el = document.getElementById(id); el.checked = on;
    el.dispatchEvent(new Event('change', {bubbles: true})); },
  slider(id, v) { const el = document.getElementById(id); el.value = v;
    el.dispatchEvent(new Event('input', {bubbles: true})); },
  click(sel) { document.querySelector(sel).click(); },
  typeSym(rating, text) { const el = document.querySelector('.cz-symbol-input[data-rating="' + rating + '"]');
    el.value = text; el.dispatchEvent(new Event('input', {bubbles: true})); },
  cubes(box) { return [...document.querySelectorAll((box || '#preview-calendar') + ' .preview-mini-cube')].map(c => ({
    filled: c.classList.contains('filled'), rating: +c.getAttribute('data-rating') || null,
    bg: getComputedStyle(c).backgroundColor, border: getComputedStyle(c).borderTopColor,
    sym: (c.querySelector('.preview-mini-sym') || {}).textContent || null,
    symColor: c.querySelector('.preview-mini-sym') ? getComputedStyle(c.querySelector('.preview-mini-sym')).color : null,
  })); },
  fills(chart, tag) { return [...document.querySelector('[data-chart="' + chart + '"]').querySelectorAll(tag)]
    .map(n => n.getAttribute('fill')); },
  card() { const c = document.getElementById('cz-preview-card');
    return {bg: getComputedStyle(c).backgroundColor, border: getComputedStyle(c).borderTopColor,
            color: getComputedStyle(c.querySelector('.cz-preview-card-title')).color}; },
  color_of(sel) { return getComputedStyle(document.querySelector(sel)).color; },
  font_of(sel) { return getComputedStyle(document.querySelector(sel)).fontFamily; },
  darkPixels(id) { const c = document.getElementById(id), x = c.getContext('2d');
    const d = x.getImageData(0, 0, c.width, c.height).data; let n = 0;
    for (let i = 0; i < d.length; i += 4) if (d[i] < 70 && d[i+1] < 70 && d[i+2] < 70 && d[i+3] > 200) n++;
    return n; },
  lightPixels(id) { const c = document.getElementById(id), x = c.getContext('2d');
    const d = x.getImageData(0, 0, c.width, c.height).data; let n = 0;
    for (let i = 0; i < d.length; i += 4) if (d[i] > 200 && d[i+1] > 200 && d[i+2] > 200 && d[i+3] > 200) n++;
    return n; },
};
"""


class Checks:
    def __init__(self):
        self.failed = []

    def __call__(self, name, cond, detail=''):
        if not cond:
            self.failed.append(f'{name}: {str(detail)[:240]}')

    def done(self):
        assert not self.failed, '\n'.join(self.failed)


def _free_port():
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


@pytest.fixture
def demo():
    """A fresh app per test; yields a function starting one with settings."""
    procs = []

    def start(settings=None):
        port = _free_port()
        args = [sys.executable, str(ROOT / 'tests' / 'browser' / '_demo_app.py'), str(port)]
        if settings:
            f = tempfile.NamedTemporaryFile('w', suffix='.json', delete=False)
            json.dump(settings, f, ensure_ascii=False)
            f.close()
            args.append(f.name)
        procs.append(subprocess.Popen(args, cwd=ROOT, stdout=subprocess.DEVNULL,
                                      stderr=subprocess.DEVNULL))
        base = f'http://127.0.0.1:{port}'
        for _ in range(300):
            try:
                urllib.request.urlopen(base + '/mood_grid', timeout=2)
                return base.replace('127.0.0.1', 'localhost')
            except Exception:
                time.sleep(0.1)
        raise RuntimeError('demo app did not start')

    yield start
    for p in procs:
        p.kill()


@pytest.fixture
def browser():
    b = Browser(port=_free_port())
    yield b
    b.close()


def _open_settings(browser, base):
    browser.goto(base + '/customization/', settle=0.8)
    browser.js(HELPERS)


def _scale_rgb(stops, rating):
    low, mid, high = stops
    pos = max(0.0, min(1.0, (rating - 1) / 9))
    a, b, k = (low, mid, pos * 2) if pos <= 0.5 else (mid, high, (pos - 0.5) * 2)
    return 'rgb(%d, %d, %d)' % tuple(round(a[i] + (b[i] - a[i]) * k) for i in range(3))


def _rgb(h):
    h = h.lstrip('#')
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


# ── the calendar, the charts that follow it, the cards ────────

def test_calendar_chart_and_card_previews(demo, browser):
    base = demo()
    _open_settings(browser, base)
    b, check = browser, Checks()
    filled = lambda cubes: {c['bg'] for c in cubes if c['filled']}
    empty = lambda cubes: {c['bg'] for c in cubes if not c['filled']}

    cubes = b.js('T.cubes()')
    check('default filled cubes', filled(cubes) == {'rgb(0, 0, 0)'}, filled(cubes))
    check('default empty cubes', empty(cubes) == {'rgb(255, 255, 255)'}, empty(cubes))
    b.js("T.color('cz-cube-filled', '#3366cc')")
    check('filled colour via picker', filled(b.js('T.cubes()')) == {'rgb(51, 102, 204)'})
    b.js("T.hex('cz-cube-filled', '#aa0000')")
    check('filled colour via hex field', filled(b.js('T.cubes()')) == {'rgb(170, 0, 0)'})

    b.js("T.toggle('cz-cube-scale', true)")
    stops = [_rgb('#c0392b'), _rgb('#e0c14a'), _rgb('#2a8f2a')]
    cubes = b.js('T.cubes()')
    check('scale on paints every filled cube its rating colour',
          all(c['bg'] == _scale_rgb(stops, c['rating']) for c in cubes if c['filled'])
          and len(filled(cubes)) > 2)
    b.js("T.color('cz-cube-scale-low', '#000000')")
    stops[0] = (0, 0, 0)
    check('the low stop repaints the preview',
          all(c['bg'] == _scale_rgb(stops, c['rating']) for c in b.js('T.cubes()') if c['filled']))
    b.js("T.hex('cz-cube-scale-high', '#ffffff')")
    stops[2] = (255, 255, 255)
    check('the high stop via hex repaints the preview',
          all(c['bg'] == _scale_rgb(stops, c['rating']) for c in b.js('T.cubes()') if c['filled']))
    mosaic = [c['bg'] for c in b.js("T.cubes('#preview-mosaic-calendar')") if c['filled']]
    cal = [c['bg'] for c in b.js('T.cubes()') if c['filled']]
    check('the mosaic preview shows the same calendar', mosaic == cal)
    b.js("T.toggle('cz-cube-scale', false)")
    check('scale off returns to the filled colour', filled(b.js('T.cubes()')) == {'rgb(170, 0, 0)'},
          filled(b.js('T.cubes()')))

    b.js("T.color('cz-cube-empty', '#00ff00')")
    check('empty colour', empty(b.js('T.cubes()')) == {'rgb(0, 255, 0)'})
    b.js("T.color('cz-cube-border', '#0000ff')")
    check('border colour', 'rgb(0, 0, 255)' in {c['border'] for c in b.js('T.cubes()')})

    b.js("T.toggle('cz-cube-symbols', true)")
    cubes = b.js('T.cubes()')
    check('symbols on: the digits', all(c['sym'] == str(c['rating']) for c in cubes if c['filled']))
    check('symbols on a dark fill are white',
          all(c['symColor'] == 'rgb(255, 255, 255)' for c in cubes if c['filled']))
    b.js("T.click('.cz-symbol-preset[data-preset=\"faces\"]')")
    check('the faces preset', all(c['sym'] and not c['sym'].isdigit()
                                  for c in b.js('T.cubes()') if c['filled']))
    b.js("T.typeSym(1, '')")
    cubes = b.js('T.cubes()')
    check('an emptied symbol disappears', any(c['rating'] == 1 for c in cubes if c['filled'])
          and all(c['sym'] is None for c in cubes if c['filled'] and c['rating'] == 1))
    b.js("T.toggle('cz-cube-symbols-hide-fill', true)")
    check('no fill under symbols', all(c['bg'] == 'rgb(0, 255, 0)'
                                       for c in b.js('T.cubes()') if c['filled'] and c['sym']))
    b.js("T.toggle('cz-cube-symbols', false)")
    cubes = b.js('T.cubes()')
    check('symbols off', all(c['sym'] is None for c in cubes) and filled(cubes) == {'rgb(170, 0, 0)'})

    b.js("T.toggle('cz-cube-scale', true)")
    grid = lambda chart, tag: any(f and f.startswith('rgb(') for f in b.js(f"T.fills('{chart}', '{tag}')"))
    check('the spiral preview follows the grid', grid('spiral', 'circle'))
    check('the overview preview follows the grid', grid('overview', 'rect'))
    check('the rose preview follows the grid', grid('rose', 'polygon'))
    b.js("T.colorKey('spiral-dot-color', '#123456')")
    spiral = set(b.js("T.fills('spiral', 'circle')"))
    check('a chosen spiral colour outranks the grid', '#123456' in spiral and not grid('spiral', 'circle'))
    b.js("T.colorKey('chart-color', '#654321')")
    check('the global chart colour outranks the grid', '#654321' in b.js("T.fills('rose', 'polygon')")
          and not grid('rose', 'polygon'))
    b.js("T.toggle('cz-cube-scale', false)")
    b.js("T.colorKey('brand-color', '#ff00ff')")
    strokes = b.js("[...document.querySelector('[data-chart=\"river\"]').querySelectorAll('line')].map(l => l.getAttribute('stroke'))")
    check("the accent colour reaches the charts' today marker", '#ff00ff' in strokes, strokes)

    b.js("T.click('.cz-card-mode-btn[data-mode=\"color\"]')")
    b.js("T.color('cz-card-bg', '#102030')")
    card = b.js('T.card()')
    check('card colour', card['bg'] == 'rgb(16, 32, 48)', card)
    check('text on a dark card turns light', card['color'] == 'rgb(255, 255, 255)', card)
    b.js("T.slider('cz-card-opacity', 50)")
    check('card opacity', b.js('T.card()')['bg'] == 'rgba(16, 32, 48, 0.5)', b.js('T.card()'))
    b.js("T.color('cz-card-border', '#ff0000')")
    check('card border', b.js('T.card()')['border'] == 'rgb(255, 0, 0)')

    # Saved, reloaded, and compared with the real calendar rating by rating.
    b.goto(base + '/customization/', settle=0.6)
    b.js(HELPERS)
    b.js("T.toggle('cz-cube-scale', true); T.toggle('cz-cube-symbols', true);")
    b.js("document.getElementById('cz-save-btn').click()")
    time.sleep(0.8)
    _open_settings(b, base)
    preview = {c['rating']: c['bg'] for c in b.js('T.cubes()') if c['filled']}
    b.goto(base + '/mood_grid/2026', settle=0.6)
    real = b.js("""(() => { const o = {}; for (let r = 1; r <= 10; r++) {
        const c = document.querySelector('.cube.filled.r' + r); if (c) o[r] = getComputedStyle(c).backgroundColor; }
        return o; })()""")
    check('the preview matches the real calendar', real and all(
        real.get(str(r)) == bg for r, bg in preview.items() if str(r) in real), (preview, real))
    check('the real calendar shows the symbols', b.js("document.querySelectorAll('.cube.filled .cube-sym').length") > 0)
    check.done()


# ── text, fonts, background, avatar, the neural map ───────────

def test_text_font_background_avatar_and_neural_previews(demo, browser):
    base = demo()
    _open_settings(browser, base)
    b, check = browser, Checks()
    col = lambda sel: b.js(f"T.color_of('{sel}')")

    b.js("T.color('cz-text-color', '#333399')")
    check('body text colour', col('#preview-font-body') == 'rgb(51, 51, 153)', col('#preview-font-body'))
    b.js("T.color('cz-heading-color', '#993333')")
    check('heading colour', col('#preview-font-heading') == 'rgb(153, 51, 51)')
    b.js("T.color('cz-text-muted', '#707070')")
    check('muted colour', col('.preview-mini-muted') == 'rgb(112, 112, 112)')
    b.js("T.color('cz-brand-color', '#ff8800')")
    check('accent colour', col('.preview-mini-link.active') == 'rgb(255, 136, 0)')
    b.js("T.color('cz-bg-color', '#101010')")
    check('a dark page rescues a dark text pick', col('#preview-font-body') == 'rgb(255, 255, 255)')
    b.js("T.toggle('cz-auto-invert', false)")
    check('with auto-invert off the pick stays', col('#preview-font-body') == 'rgb(51, 51, 153)')
    b.js("T.toggle('cz-auto-invert', true)")
    b.js("T.color('cz-text-color', '#ffe680')")
    check('a readable light pick on a dark page is kept', col('#preview-font-body') == 'rgb(255, 230, 128)')
    b.js("T.color('cz-bg-color', '#ffffff')")
    check('on white the light pick is rescued', col('#preview-font-body') == 'rgb(0, 0, 0)')

    before = b.js("T.font_of('#preview-font-body')")
    b.js("(() => { const s = document.getElementById('cz-font-body'); s.value = [...s.options].find(o => o.value !== 'times' && o.value !== 'custom').value; s.dispatchEvent(new Event('change', {bubbles: true})); })()")
    time.sleep(0.3)
    check('body font', b.js("T.font_of('#preview-font-body')") != before)
    before = b.js("T.font_of('#preview-font-heading')")
    b.js("(() => { const s = document.getElementById('cz-font-heading'); s.value = [...s.options].reverse().find(o => o.value !== 'times' && o.value !== 'custom').value; s.dispatchEvent(new Event('change', {bubbles: true})); })()")
    time.sleep(0.3)
    check('heading font', b.js("T.font_of('#preview-font-heading')") != before)
    b.js("T.toggle('cz-notes-use-body', true)")
    time.sleep(0.2)
    check('notes follow the body font', b.js("T.font_of('#preview-font-notes')") == b.js("T.font_of('#preview-font-body')"))

    bgimg = lambda: b.js("getComputedStyle(document.documentElement).getPropertyValue('--bg-image')")
    b.js("T.click('.cz-bg-type-btn[data-type=\"gradient\"]')")
    check('gradient background', 'linear-gradient' in bgimg(), bgimg())
    b.js("T.slider('cz-grad-angle', 90)")
    check('gradient angle', '90deg' in bgimg(), bgimg())
    b.js("T.click('.cz-bg-shape-btn[data-shape=\"radial\"]')")
    check('radial gradient', 'radial-gradient' in bgimg(), bgimg())
    time.sleep(0.4)   # the buttons animate their background
    check('the chosen shape looks chosen', b.js("getComputedStyle(document.querySelector('.cz-bg-shape-btn.active')).backgroundColor") == 'rgb(34, 34, 34)')
    b.js("T.click('.cz-bg-type-btn[data-type=\"color\"]')")
    check('back to a plain colour', 'gradient' not in bgimg(), bgimg())

    avatar = lambda: b.js("(() => { const s = getComputedStyle(document.getElementById('cz-avatar-preview')); return s.backgroundColor + ' ' + s.backgroundImage; })()")
    b.js("T.color('cz-avatar-color', '#00aa55')")
    check('avatar colour', 'rgb(0, 170, 85)' in avatar(), avatar())
    b.js("T.click('.cz-avatar-type-btn[data-type=\"gradient\"]')")
    b.js("T.color('cz-avatar-grad-from', '#112233')")
    check('avatar gradient', 'gradient' in avatar() and 'rgb(17, 34, 51)' in avatar(), avatar())
    time.sleep(0.4)
    check('the chosen avatar type looks chosen', b.js("getComputedStyle(document.querySelector('.cz-avatar-type-btn.active')).backgroundColor") == 'rgb(34, 34, 34)')

    snap = lambda: b.js("document.getElementById('preview-neural').toDataURL()")
    s0 = snap()
    b.js("T.color('cz-neural-node', '#ff0000')")
    check('node colour redraws the map', snap() != s0)
    check.done()


def test_neural_map_labels_follow_the_canvas_not_the_page(demo, browser):
    """A black page turns the page text white; the map's labels sit on its
    own near-white canvas and must stay dark there."""
    base = demo()
    _open_settings(browser, base)
    b, check = browser, Checks()
    # Nodes and edges red, so the only near-black pixels are label text.
    for key in ('cz-neural-node', 'cz-neural-active', 'cz-neural-edge'):
        b.js(f"T.color('{key}', '#ff0000')")
    b.js("T.color('cz-bg-color', '#000000')")
    check('dark labels on the light canvas of a dark page', b.js("T.darkPixels('preview-neural')") > 20,
          b.js("T.darkPixels('preview-neural')"))
    b.js("T.color('cz-neural-canvas', '#101010')")
    check('light labels once the canvas is dark too', b.js("T.lightPixels('preview-neural')") > 20,
          b.js("T.lightPixels('preview-neural')"))
    check.done()

    # The real page: the map reads its label colour from its container.
    base = demo({'bg-type': 'color', 'bg-color': '#000000'})
    b.goto(base + '/graphics', settle=0.4)
    css = b.js("document.getElementById('customization-vars').textContent")
    assert 'html #graph-container{--text-color:#000000' in css
