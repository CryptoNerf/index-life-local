"""Both "people" detail pages must render against the real app factory.

Regression: `plain_text` was imported inside my_people_detail only, so the
assistant-people detail page (people_detail) raised NameError — every click
on a name showed "Something went wrong". A unit test on the helper couldn't
see that; only rendering the pages through the registered blueprint does.

Runs in a subprocess: the real create_app() freezes config.BASE_DIR at
import time, and importing it in-process while paths.user_data_dir is
patched would poison the resolver-unification test that runs later.
"""
import subprocess
import sys
from pathlib import Path

_SCRIPT = r'''
import os, sys, tempfile
from datetime import date
from pathlib import Path

tmp = Path(tempfile.mkdtemp())
(tmp / 'graphics_enabled').write_text('1')
os.environ['SECRET_KEY'] = 'test'
import paths
paths.user_data_dir = lambda: tmp

from app import create_app, db
application = create_app()
assert 'graphics' in application.config.get('ACTIVE_MODULES', []), 'graphics inactive'

from app.models import MoodEntry, EntryPerson, UserPerson
with application.app_context():
    entry = MoodEntry(date=date(2026, 7, 10), rating=7,
                      note='Гулял с Машей по набережной. Маша смеялась.')
    db.session.add(entry)
    db.session.flush()
    db.session.add(EntryPerson(entry_id=entry.id, mention='маша', tone='positive'))
    person = UserPerson(name='Маша')
    db.session.add(person)
    db.session.commit()
    person_id = person.id

client = application.test_client()

r = client.get('/graphics/people/detail?name=маша')
assert r.status_code == 200, f'people_detail -> {r.status_code}'
assert 'Гулял с Машей'.encode() in r.data, 'note text missing on people_detail'

r = client.get(f'/graphics/my-people/{person_id}')
assert r.status_code == 200, f'my_people_detail -> {r.status_code}'
assert b'mpd-hit' in r.data, 'mention highlight missing'
assert 'по набережной'.encode() in r.data, 'note text missing on my_people_detail'

print('PEOPLE_PAGES_OK')
'''


def test_people_detail_pages_render_in_the_real_app():
    result = subprocess.run(
        [sys.executable, '-c', _SCRIPT],
        cwd=Path(__file__).resolve().parent.parent,
        capture_output=True, text=True, timeout=180,
    )
    assert result.returncode == 0, f'stderr:\n{result.stderr[-2000:]}'
    assert 'PEOPLE_PAGES_OK' in result.stdout
