"""Two small edges of the main pages.

* The day editor restores an unsaved draft from the browser. It did so even
  when the saved entry was newer — typed here, not saved, then the same day
  written on the phone: the old draft came back over the phone's text and
  Save overwrote it. The page now gets the entry's last write time so a
  draft only wins while it is the fresher of the two (the PWA's rule).
* /mood_grid/<year> built the whole year before checking it, so a year past
  9999 was a server error rather than a redirect.
"""
import calendar
import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import pytest

# The pages need the real app factory (i18n, the header's blueprints), which
# runs migrations against a data dir — so they are rendered in a subprocess
# with a throwaway one, as the weather page test does.
_SCRIPT = r"""
import json, os, sys, tempfile
from datetime import date, datetime
from pathlib import Path
tmp = Path(tempfile.mkdtemp())
os.environ['SECRET_KEY'] = 'test'
import paths
paths.user_data_dir = lambda: tmp
from app import create_app, db
from app.models import MoodEntry
application = create_app()
with application.app_context():
    db.session.add(MoodEntry(date=date(2026, 9, 20), rating=7, note='текст',
                             updated_at=datetime(2026, 9, 20, 18, 30, 5)))
    db.session.add(MoodEntry(date=date(2026, 9, 22), rating=7, note='было',
                             deleted=True, updated_at=datetime(2026, 9, 22, 9, 0, 0)))
    db.session.commit()
c = application.test_client()
out = {
    'saved': c.get('/day/2026-09-20').get_data(as_text=True),
    'new': c.get('/day/2026-09-21').get_data(as_text=True),
    'deleted': c.get('/day/2026-09-22').get_data(as_text=True),
    'years': {y: c.get('/mood_grid/%d' % y).status_code for y in (10000, 99999, 0)},
}
print(json.dumps(out))
"""


@pytest.fixture(scope='module')
def pages():
    root = Path(__file__).resolve().parents[1]
    r = subprocess.run([sys.executable, '-c', _SCRIPT], cwd=root,
                       capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr[-2000:]
    return json.loads(r.stdout.strip().splitlines()[-1])


def _ms(dt):
    return calendar.timegm(dt.timetuple()) * 1000


def _entry_updated_ms(body: str):
    m = re.search(r'const ENTRY_UPDATED_MS = (null|\d+);', body)
    assert m, 'the page no longer tells the draft logic when the entry was saved'
    return None if m.group(1) == 'null' else int(m.group(1))


def test_the_editor_knows_when_the_entry_was_last_written(pages):
    assert _entry_updated_ms(pages['saved']) == _ms(datetime(2026, 9, 20, 18, 30, 5))


def test_a_new_day_has_nothing_for_a_draft_to_lose_to(pages):
    assert _entry_updated_ms(pages['new']) is None


def test_a_day_deleted_elsewhere_still_outdates_an_older_draft(pages):
    body = pages['deleted']
    assert _entry_updated_ms(body) == _ms(datetime(2026, 9, 22, 9, 0, 0))
    textarea = body.split('<textarea', 1)[1].split('</textarea>', 1)[0]
    assert 'было' not in textarea


def test_a_refused_save_does_not_throw_the_draft_away(pages):
    """The draft is cleared only on the path where the form really goes."""
    script = pages['new'][pages['new'].index('Tiptap Editor Setup'):]
    sync_handler = script[script.index('Sync the editor into the form'):
                          script.index('// Form validation')]
    assert 'clearDraft()' not in sync_handler
    validation = script[script.index('// Form validation'):]
    assert validation.index('return false;') < validation.index('clearDraft();')


def test_an_impossible_year_redirects_instead_of_failing(pages):
    assert set(pages['years'].values()) == {302}, pages['years']
