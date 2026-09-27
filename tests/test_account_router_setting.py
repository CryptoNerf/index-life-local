"""The account page, rendered by the real app, offers the router choice.

Run in a subprocess against the real app factory, like the other page tests:
the bare `app` fixture has no i18n and none of the blueprints the page links
to. The first version of this section broke the whole page (a later local
import in the view shadowed `current_app`), and no test opened the page.
"""
import subprocess
import sys
from pathlib import Path

_SCRIPT = r'''
import os, re, sys, tempfile
from pathlib import Path

tmp = Path(tempfile.mkdtemp())
os.environ['SECRET_KEY'] = 'test'
os.environ.pop('ASSISTANT_ROUTER', None)
import paths
paths.user_data_dir = lambda: tmp

from app import create_app, db
application = create_app()
from app.models import UserProfile
with application.app_context():
    UserProfile.query.first().language = 'ru'
    db.session.commit()
client = application.test_client()

def choice():
    resp = client.get('/account')
    assert resp.status_code == 200, resp.status_code
    html = resp.get_data(as_text=True)
    i = html.find('Как психолог собирает данные')
    return i, re.findall(r'value="(\w+)"\s*checked', html[i:i + 2000])

if 'assistant' not in application.config.get('ACTIVE_MODULES', []):
    # Without the module the page must still render, just without the section.
    i, _ = choice()
    assert i == -1
    print('ACCOUNT_OK no assistant', flush=True)
    sys.exit(0)

i, checked = choice()
assert i != -1, 'section missing'
assert checked == ['scenario'], checked          # the default
resp = client.post('/assistant/set-router-mode', data={'mode': 'legacy'},
                   headers={'Origin': 'http://localhost'})
assert resp.status_code == 302
assert choice()[1] == ['legacy']
print('ACCOUNT_OK', flush=True)
os._exit(0)
'''


def test_the_account_page_offers_and_keeps_the_router_choice():
    result = subprocess.run(
        [sys.executable, '-c', _SCRIPT],
        cwd=Path(__file__).resolve().parent.parent,
        capture_output=True, text=True, timeout=300,
    )
    assert result.returncode == 0, f'stderr:\n{result.stderr[-3000:]}'
    assert 'ACCOUNT_OK' in result.stdout
