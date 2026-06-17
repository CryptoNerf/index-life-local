"""Regression tests for the code-review quick-win fixes.

Covers three independent fixes:

  * #1 — the AI-psychologist tool router must degrade gracefully (return
    []/None) when the router LLM raises or emits junk, instead of blowing
    up the whole chat turn with a NameError from a missing `logging`
    import.
  * #2 — soft-deleted (tombstone) entries must NOT leak into the
    neural-map clustering source.
  * #3 — the cached embedding matrix must be rebuilt after an in-place
    re-embed of an edited entry, not only when the row count changes.
"""
from datetime import date

import numpy as np
import pytest


# ── Fix #1: tool router survives a failing / malformed router LLM ──────────

class _BoomLLM:
    """Stand-in LLM whose completion call always raises."""

    def create_chat_completion(self, **kwargs):
        raise RuntimeError('router model exploded')


def test_route_to_tools_survives_llm_failure():
    """A raising router LLM should yield an empty tool list, not NameError."""
    from app.modules.assistant.routes import _route_to_tools

    # Long enough to clear the trivial-length short-circuit in the router.
    msg = 'Что я писал про маму в марте прошлого года и какое было настроение?'
    assert _route_to_tools(_BoomLLM(), msg) == []


def test_execute_tool_survives_failure_without_app_context():
    """A tool that raises (here: DB access outside app context) must be
    swallowed and return None — the except path references the module
    logger that previously was never imported."""
    from app.modules.assistant.routes import _execute_tool

    assert _execute_tool('person_history', {'name': 'тест'}) is None


# ── Fix #2: neural-map clustering ignores soft-deleted entries ─────────────

def test_load_embeddings_excludes_soft_deleted(app):
    from app import db
    from app.models import MoodEntry, EntryEmbedding
    from app.modules.deep_mind.clustering import load_embeddings

    live = MoodEntry(date=date(2026, 1, 1), rating=5, note='живая запись', deleted=False)
    dead = MoodEntry(date=date(2026, 1, 2), rating=3, note='удалённая запись', deleted=True)
    db.session.add_all([live, dead])
    db.session.commit()

    for e in (live, dead):
        db.session.add(EntryEmbedding(
            entry_id=e.id,
            embedding=np.zeros(384, dtype=np.float32).tobytes(),
            text_hash='h',
        ))
    db.session.commit()

    entry_ids, matrix = load_embeddings()

    assert live.id in entry_ids
    assert dead.id not in entry_ids
    assert matrix.shape == (1, 384)


def test_load_embeddings_skips_empty_notes(app):
    """A blank/whitespace note is still skipped after the join refactor."""
    from app import db
    from app.models import MoodEntry, EntryEmbedding
    from app.modules.deep_mind.clustering import load_embeddings

    blank = MoodEntry(date=date(2026, 3, 1), rating=5, note='   ', deleted=False)
    db.session.add(blank)
    db.session.commit()
    db.session.add(EntryEmbedding(
        entry_id=blank.id,
        embedding=np.zeros(384, dtype=np.float32).tobytes(),
        text_hash='h',
    ))
    db.session.commit()

    entry_ids, matrix = load_embeddings()
    assert entry_ids == []
    assert matrix.shape == (0, 384)


# ── Fix #3: embedding cache rebuilds on in-place re-embed ──────────────────

def test_embedding_cache_rebuilds_after_invalidation(app):
    from app import db
    from app.models import MoodEntry, EntryEmbedding
    from app.modules.assistant import memory

    e = MoodEntry(date=date(2026, 2, 1), rating=5, note='x', deleted=False)
    db.session.add(e)
    db.session.commit()
    db.session.add(EntryEmbedding(
        entry_id=e.id,
        embedding=np.ones(384, dtype=np.float32).tobytes(),
        text_hash='h1',
    ))
    db.session.commit()

    # Force a rebuild from this test's DB (module globals persist across tests).
    memory._invalidate_embedding_cache()
    _ids, mat = memory._get_embedding_matrix()
    assert mat[0][0] == pytest.approx(1.0)

    # In-place re-embed: row count is unchanged, only the bytes differ —
    # exactly the edit case the old count-only invalidation missed.
    emb = EntryEmbedding.query.filter_by(entry_id=e.id).first()
    emb.embedding = (np.ones(384, dtype=np.float32) * 7.0).tobytes()
    emb.text_hash = 'h2'
    db.session.commit()

    # Without invalidation the stale matrix is returned (documents the bug).
    _ids2, mat2 = memory._get_embedding_matrix()
    assert mat2[0][0] == pytest.approx(1.0)

    # update_embedding now calls this after every write → fresh vector.
    memory._invalidate_embedding_cache()
    _ids3, mat3 = memory._get_embedding_matrix()
    assert mat3[0][0] == pytest.approx(7.0)


# ── Fix #6: per-install Flask secret key (no shared hardcoded default) ──────

def test_secret_key_is_persistent_random_and_unique(tmp_path):
    from app import _load_or_create_secret_key

    k1 = _load_or_create_secret_key(tmp_path)
    assert isinstance(k1, str) and len(k1) >= 32
    assert k1 != 'dev-secret-key-change-in-production'

    # Persisted to disk and stable across calls (so restarts keep the key).
    assert (tmp_path / 'secret_key').read_text(encoding='utf-8').strip() == k1
    assert _load_or_create_secret_key(tmp_path) == k1

    # A separate install directory gets its own independent key.
    other = tmp_path / 'other'
    other.mkdir()
    assert _load_or_create_secret_key(other) != k1


# ── Fix #6: warn on plaintext (non-HTTPS) WebDAV sync ──────────────────────

def test_is_webdav_insecure():
    from app.sync import is_webdav_insecure

    # Remote http → credentials + diary travel in clear text.
    assert is_webdav_insecure('webdav', 'http://dav.example.com/diary/') is True
    assert is_webdav_insecure('webdav', 'dav.example.com/diary/') is True  # no scheme

    # https is fine.
    assert is_webdav_insecure('webdav', 'https://dav.example.com/diary/') is False

    # Loopback never leaves the machine → exempt even over http.
    assert is_webdav_insecure('webdav', 'http://127.0.0.1:8080/dav/') is False
    assert is_webdav_insecure('webdav', 'http://localhost/dav/') is False

    # Local-folder sync and empty URLs are not a WebDAV concern.
    assert is_webdav_insecure('local', 'http://dav.example.com/') is False
    assert is_webdav_insecure('webdav', '') is False


# ── Fix #4: neural-map auto-analysis is debounced (purely count-based) ──────

def test_deep_mind_auto_run_is_debounced(app):
    from datetime import date

    from app import db
    from app.models import MoodEntry
    from app.modules.deep_mind import background as dm

    def add_entries(n, start_day):
        for i in range(n):
            db.session.add(MoodEntry(date=date(2026, 4, start_day + i),
                                     rating=5, note='x', deleted=False))
        db.session.commit()

    # 1. No run recorded yet → the first analysis always proceeds.
    assert dm._should_auto_run() is True

    # Record a baseline run at the current entry count.
    add_entries(3, start_day=1)
    dm._record_run()

    # 2. Right after, with no new entries → debounced.
    assert dm._should_auto_run() is False

    # 3. Fewer than _MIN_NEW_ENTRIES new entries → still debounced.
    add_entries(dm._MIN_NEW_ENTRIES - 1, start_day=10)
    assert dm._should_auto_run() is False

    # 4. One more crosses the threshold → run again.
    add_entries(1, start_day=20)
    assert dm._should_auto_run() is True

    # 5. Recording the run resets the delta → debounced again.
    dm._record_run()
    assert dm._should_auto_run() is False

    # Time never matters: there is no elapsed-time path anymore.
    assert not hasattr(dm, '_MIN_INTERVAL_HOURS')
