"""A throwaway app with a year of entries, for the browser tests.

argv: port [settings.json]. Runs the real app factory on a temporary data
folder with the graphics and customization modules switched on.
"""
import json
import os
import random
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

tmp = Path(tempfile.mkdtemp())
for sentinel in ('customization_enabled', 'graphics_enabled'):
    (tmp / sentinel).write_text('1')
os.environ['SECRET_KEY'] = 'browser-tests'
sys.path.insert(0, os.getcwd())
import paths  # noqa: E402
paths.user_data_dir = lambda: tmp
from app import create_app, db  # noqa: E402
from app.models import MoodEntry, UserCustomization, UserProfile  # noqa: E402

app = create_app()
random.seed(3)
with app.app_context():
    d = date(2025, 10, 1)
    while d <= date(2026, 9, 25):
        if random.random() < 0.85:
            db.session.add(MoodEntry(date=d, note='Обычный день.',
                                     rating=max(1, min(10, round(random.gauss(6, 2))))))
        d += timedelta(days=1)
    UserProfile.query.first().language = 'ru'
    settings = json.load(open(sys.argv[2])) if len(sys.argv) > 2 else {}
    db.session.add(UserCustomization(settings_json=json.dumps(settings, ensure_ascii=False)))
    db.session.commit()
app.run(port=int(sys.argv[1]), use_reloader=False)
