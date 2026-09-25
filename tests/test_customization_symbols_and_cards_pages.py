"""Symbols in day cells and card colours, through the real app.

The composer functions are tested directly in test_customization_css.py;
here the whole path runs: the settings page renders the new controls, the
save API accepts good values and refuses bad ones, and the calendar puts
the symbols into the cells — escaped, since a symbol is whatever the user
typed.
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

_SCRIPT = r"""
import json, os, tempfile
from datetime import date
from pathlib import Path
tmp = Path(tempfile.mkdtemp())
(tmp / 'customization_enabled').write_text('1')
os.environ['SECRET_KEY'] = 'test'
import paths
paths.user_data_dir = lambda: tmp
from app import create_app, db
from app.models import MoodEntry
application = create_app()
assert 'customization' in application.config.get('ACTIVE_MODULES', []), 'customization inactive'
with application.app_context():
    db.session.add(MoodEntry(date=date(2026, 3, 1), rating=1, note='x'))
    db.session.add(MoodEntry(date=date(2026, 3, 2), rating=2, note='x'))
    db.session.add(MoodEntry(date=date(2026, 3, 3), rating=3, note='x'))
    db.session.commit()
c = application.test_client()
H = {'Content-Type': 'application/json', 'Origin': 'http://localhost'}

def save(settings):
    r = c.post('/customization/api/save', data=json.dumps({'settings': settings}),
               headers=H, base_url='http://localhost')
    return r.get_json()

out = {}
out['settings_page'] = c.get('/customization/', base_url='http://localhost').get_data(as_text=True)
out['grid_before'] = c.get('/mood_grid/2026', base_url='http://localhost').get_data(as_text=True)
symbols = ['😭', '<b>', '', '', '', '', '', '', '', '🤩']
out['save_ok'] = save({'cube-symbols-enabled': 'true',
                       'cube-symbols': json.dumps(symbols, ensure_ascii=False)})
out['save_bad'] = save({'cube-symbols': '["only", "two"]', 'card-bg-mode': 'sideways'})
out['grid_after'] = c.get('/mood_grid/2026', base_url='http://localhost').get_data(as_text=True)
out['save_cards'] = save({'card-bg-mode': 'color', 'card-bg-color': '#102030',
                          'card-bg-opacity': '0.5'})
out['grid_cards'] = c.get('/mood_grid/2026', base_url='http://localhost').get_data(as_text=True)
print(json.dumps(out, ensure_ascii=False))
"""


@pytest.fixture(scope='module')
def run():
    root = Path(__file__).resolve().parents[1]
    r = subprocess.run([sys.executable, '-c', _SCRIPT], cwd=root,
                       capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr[-3000:]
    return json.loads(r.stdout.strip().splitlines()[-1])


def test_the_settings_page_offers_symbols_and_cards(run):
    page = run['settings_page']
    assert 'id="cz-cube-symbols"' in page
    assert page.count('class="cz-symbol-input"') == 10
    assert 'id="sec-cards"' in page and 'data-key="card-bg-mode"' in page
    assert 'id="cz-auto-invert"' in page and 'checked' in page.split('id="cz-auto-invert"')[1][:200], \
        'auto-invert should be on by default'


def test_no_symbols_until_they_are_switched_on(run):
    assert 'cube-sym' not in run['grid_before'].split('<body', 1)[1]


def test_good_values_are_saved_and_bad_ones_refused(run):
    assert run['save_ok']['ok'] and not run['save_ok']['rejected']
    assert sorted(run['save_bad']['rejected']) == ['card-bg-mode', 'cube-symbols']


def test_the_calendar_shows_each_ratings_symbol(run):
    body = run['grid_after'].split('<body', 1)[1]
    assert '<span class="cube-sym">😭</span>' in body          # rating 1
    assert '<span class="cube-sym">🤩</span>' not in body      # no ten in the diary
    assert body.count('has-sym') == 2, 'rating 3 has an empty symbol and gets none'


def test_a_symbol_is_text_not_markup(run):
    body = run['grid_after'].split('<body', 1)[1]
    assert '&lt;b&gt;' in body
    assert '<b>' not in body


def test_card_colours_reach_the_page(run):
    assert run['save_cards']['ok']
    assert 'background:rgba(16,32,48,0.5)' in run['grid_cards']
