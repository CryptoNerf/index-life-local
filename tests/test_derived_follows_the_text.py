"""What the assistant indexed from a day must follow that day's text.

A local edit rebuilds the index on save. A change arriving through sync did
not: the scans that fill the index only look for entries with no index at
all, so a day rewritten on the phone kept answering questions with what it
used to say. A deleted day was worse — its summary still fed the monthly
summaries and the psychological profile, and the background worker spent
model time indexing tombstones.
"""
import json
from datetime import date

import pytest

from app import db, sync
from app.models import (EntryActivity, EntryEmbedding, EntryIndexMark,
                        EntryPerson, EntrySummary, MindCluster,
                        MindClusterEntry, MoodEntry, SyncMeta)
from app.timeutil import utcnow

DAY = date(2026, 9, 20)


@pytest.fixture
def indexed(app):
    """A day with every kind of derived row the assistant writes."""
    db.session.add(SyncMeta(key='device_id', value='desktop'))
    e = MoodEntry(date=DAY, rating=6, note='гуляли с Машей в парке',
                  uuid='u-1', updated_at=utcnow().replace(year=2026, month=9, day=20))
    db.session.add(e)
    db.session.flush()
    cluster = MindCluster(label='Прогулки')
    db.session.add(cluster)
    db.session.flush()
    db.session.add_all([
        EntrySummary(entry_id=e.id, summary='прогулка с Машей'),
        EntryEmbedding(entry_id=e.id, embedding=b'\0' * 8, text_hash='x'),
        EntryPerson(entry_id=e.id, mention='Маша', tone='neutral'),
        EntryActivity(entry_id=e.id, activity='прогулка'),
        EntryIndexMark(entry_id=e.id, kind='people'),
        MindClusterEntry(cluster_id=cluster.id, entry_id=e.id),
    ])
    db.session.commit()
    return e.id


def _derived(entry_id):
    return {m.__name__: m.query.filter_by(entry_id=entry_id).count()
            for m in (EntrySummary, EntryEmbedding, EntryPerson,
                      EntryActivity, EntryIndexMark, MindClusterEntry)}


def _peer_says(note=None, deleted=False, rating=6):
    return {
        'snapshot_version': 4, 'device_id': 'phone',
        'mood_entries': [{
            'uuid': 'u-1', 'date': DAY.isoformat(), 'rating': rating,
            'note': note, 'deleted': deleted, 'device_id': 'phone',
            'created_at': '2026-09-20T20:00:00',
            'updated_at': '2099-01-01T00:00:00',      # newer than anything local
        }],
    }


# ── through sync ──────────────────────────────────────────────

def test_a_day_rewritten_on_the_phone_loses_its_old_index(app, indexed):
    sync.apply_snapshot(_peer_says(note='весь день работал, устал'))

    assert set(_derived(indexed).values()) == {0}, _derived(indexed)


def test_a_day_deleted_on_the_phone_loses_its_index(app, indexed):
    sync.apply_snapshot(_peer_says(note='гуляли с Машей в парке', deleted=True))

    assert set(_derived(indexed).values()) == {0}, _derived(indexed)


def test_a_rating_change_alone_keeps_the_index(app, indexed):
    """The text is what was indexed; re-running the model over identical
    text would cost minutes and change nothing."""
    sync.apply_snapshot(_peer_says(note='гуляли с Машей в парке', rating=9))

    assert set(_derived(indexed).values()) == {1}, _derived(indexed)


def test_an_older_peer_version_touches_nothing(app, indexed):
    stale = _peer_says(note='совсем другой текст')
    stale['mood_entries'][0]['updated_at'] = '2020-01-01T00:00:00'

    sync.apply_snapshot(stale)

    assert set(_derived(indexed).values()) == {1}


# ── locally ───────────────────────────────────────────────────

def test_deleting_a_day_here_drops_its_index(app, indexed):
    from app.routes import bp
    app.config['SECRET_KEY'] = 'test'
    app.register_blueprint(bp)

    r = app.test_client().post(f'/day/{DAY.isoformat()}/delete')

    assert r.status_code == 302
    assert db.session.get(MoodEntry, indexed).deleted is True
    assert set(_derived(indexed).values()) == {0}, _derived(indexed)


# ── the scans leave deleted days alone ────────────────────────

def test_the_people_backfill_skips_deleted_days(app, monkeypatch):
    from app.modules.assistant import background as bg
    import app.modules.assistant.memory as mem
    import app.modules.assistant.routes as routes

    live = MoodEntry(date=date(2026, 9, 1), rating=6, note='живой день')
    gone = MoodEntry(date=date(2026, 9, 2), rating=6, note='удалённый день',
                     deleted=True)
    db.session.add_all([live, gone])
    db.session.commit()

    asked = []
    monkeypatch.setattr(mem, 'extract_people_mentions',
                        lambda entry, llm: asked.append(entry.id), raising=False)
    monkeypatch.setattr(routes, '_get_llm', lambda: object(), raising=False)
    monkeypatch.setattr(bg, '_extract_yield', lambda: 0.0)
    monkeypatch.setattr(bg, '_wait_if_chat_active', lambda: None)

    bg._backfill_people(app)

    assert asked == [live.id]


def test_the_month_summary_does_not_read_deleted_days(app):
    from app.modules.assistant import memory

    db.session.add_all([
        MoodEntry(date=date(2026, 9, 1), rating=6, note='остался'),
        MoodEntry(date=date(2026, 9, 2), rating=2, note='СЕКРЕТ удалён',
                  deleted=True),
    ])
    db.session.commit()

    prompts = []

    class _LLM:
        def create_chat_completion(self, messages, **kw):
            prompts.append(json.dumps(messages, ensure_ascii=False))
            return {'choices': [{'message': {'content': 'Сводка месяца.'}}]}

        def __call__(self, prompt, **kw):
            prompts.append(prompt)
            return {'choices': [{'text': 'Сводка месяца.'}]}

    try:
        memory.generate_month_summary(2026, 9, _LLM())
    except Exception:
        pass    # whatever the stub cannot satisfy, the prompt is what matters

    assert prompts, 'the summary never asked the model'
    assert not any('СЕКРЕТ' in p for p in prompts), 'a deleted day reached the model'
