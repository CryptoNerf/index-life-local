"""Chat-history pruning routes (assistant module).

Both /assistant/clear-chat and /assistant/compress-chat must record the
`chat_cleared_at` sync cutoff: the chat merge is append-only by uuid, so
without the mark the next sync pull re-imports every pruned message from
peer snapshots — silently undoing the clear/compression.
"""
from datetime import timedelta

import pytest

from app import db, sync
from app.models import ChatMessage, SyncMeta
from app.timeutil import utcnow


@pytest.fixture
def client(app):
    from app.modules.assistant import init_app
    init_app(app)
    return app.test_client()


def _add_messages(n, start):
    for i in range(n):
        db.session.add(ChatMessage(
            role='user', content=f'm{i}',
            created_at=start + timedelta(minutes=i),
            uuid=f'local-m{i}',
        ))
    db.session.commit()


def _peer_snapshot(messages):
    return {
        'snapshot_version': 4,
        'device_id': 'peer1',
        'generated_at': utcnow().isoformat(),
        'mood_entries': [],
        'chat_messages': messages,
        'user_profile': None,
    }


def _peer_msg(uuid, content, created_at):
    return {
        'uuid': uuid, 'role': 'user', 'content': content,
        'created_at': created_at.isoformat(), 'device_id': 'peer1',
    }


# ── compress-chat ─────────────────────────────────────────────

def test_compress_keeps_last_four_and_records_cutoff(client):
    start = utcnow() - timedelta(hours=1)
    _add_messages(6, start)

    resp = client.post('/assistant/compress-chat')

    assert resp.get_json() == {'status': 'ok', 'removed': 2, 'remaining': 4}
    assert {m.content for m in ChatMessage.query.all()} == {'m2', 'm3', 'm4', 'm5'}
    assert db.session.get(SyncMeta, 'chat_cleared_at') is not None


def test_compress_is_a_noop_below_the_threshold(client):
    start = utcnow() - timedelta(hours=1)
    _add_messages(3, start)

    resp = client.post('/assistant/compress-chat')

    assert resp.get_json() == {'status': 'ok', 'removed': 0, 'remaining': 3}
    assert ChatMessage.query.count() == 3
    # nothing was pruned — no cutoff, peers keep syncing history freely
    assert db.session.get(SyncMeta, 'chat_cleared_at') is None


def test_peer_snapshot_cannot_resurrect_compressed_messages(client):
    """Regression: compress → sync pull used to re-import the pruned
    messages from a peer snapshot, silently undoing the compression."""
    start = utcnow() - timedelta(hours=1)
    _add_messages(6, start)
    client.post('/assistant/compress-chat')

    stats = sync.apply_snapshot(_peer_snapshot([
        # the peer still has a message we just compressed away
        _peer_msg('peer-old', 'm0', start),
        # ...and a genuinely new one from after the compression
        _peer_msg('peer-new', 'fresh', utcnow() + timedelta(minutes=1)),
    ]))

    contents = {m.content for m in ChatMessage.query.all()}
    assert 'm0' not in contents          # stays compressed
    assert 'fresh' in contents           # new messages keep syncing
    assert stats['chat_inserted'] == 1


# ── clear-chat ────────────────────────────────────────────────

def test_clear_chat_removes_everything_and_records_cutoff(client):
    start = utcnow() - timedelta(hours=1)
    _add_messages(3, start)

    resp = client.post('/assistant/clear-chat')

    assert resp.get_json() == {'status': 'ok'}
    assert ChatMessage.query.count() == 0
    assert db.session.get(SyncMeta, 'chat_cleared_at') is not None

    stats = sync.apply_snapshot(_peer_snapshot([
        _peer_msg('peer-old', 'm0', start),
    ]))
    assert ChatMessage.query.count() == 0
    assert stats['chat_inserted'] == 0
