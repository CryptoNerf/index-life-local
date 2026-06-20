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

Later turns added regressions for further review fixes (paths consolidation,
llm_text helpers, debounce, secret key, tools split, log rotation, embed
worker respawn). One file keeps them discoverable together.
"""
import json
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


# ── Fix #7: a single data-dir resolver (no divergent copies) ───────────────

def test_data_dir_resolvers_are_unified():
    """Every data-dir entry point must resolve to the one place in paths.py.

    Before the consolidation `app.modules._get_user_data_dir` was a second
    copy that returned the platform app-data dir in a source checkout, while
    config used the repo root — this asserts they can no longer diverge.
    """
    import config
    import app as app_pkg
    from app.modules import _get_user_data_dir
    from paths import user_data_dir, BASE_DIR

    canonical = user_data_dir()
    assert config._resolve_data_dir() == canonical
    assert config.BASE_DIR == canonical
    assert config.DATA_DIR == canonical
    assert _get_user_data_dir() == canonical
    assert app_pkg._get_data_dir() == canonical
    # Tests run non-frozen, so the canonical dir is the repo root.
    assert canonical == BASE_DIR


# ── #11(c): shared LLM text helpers (single impl; head/tail truncation) ─────

class _CharLLM:
    """Toy LLM whose tokenizer maps each UTF-8 byte to one token, so
    truncation is exact and direction is observable in tests."""

    def tokenize(self, b):
        return list(b)

    def detokenize(self, tokens):
        return bytes(tokens)


def test_strip_think_handles_open_closed_and_stray_tags():
    from app.modules.assistant.llm_text import strip_think

    assert strip_think('<think>reasoning</think>answer') == 'answer'
    assert strip_think('before<think>x</think>after') == 'beforeafter'
    assert strip_think('hi<think>ran out of tokens') == 'hi'   # unclosed block
    assert strip_think('done</think>') == 'done'               # stray close tag
    assert strip_think('') == ''
    assert strip_think(None) == ''


def test_truncate_to_tokens_keeps_correct_end():
    """The whole point of centralising: head keeps the start (prompt
    trimming), tail keeps the end (most recent summaries). These used to be
    two separate functions that silently disagreed."""
    from app.modules.assistant.llm_text import truncate_to_tokens, count_tokens

    llm = _CharLLM()
    text = 'abcdefgh'  # 8 ascii bytes → 8 tokens
    assert count_tokens(llm, text) == 8

    assert truncate_to_tokens(llm, text, 3, keep='head') == 'abc'
    assert truncate_to_tokens(llm, text, 3, keep='tail') == 'fgh'
    assert truncate_to_tokens(llm, text, 3) == 'abc'           # default = head
    assert truncate_to_tokens(llm, text, 100) == text          # already fits
    assert truncate_to_tokens(llm, text, 0) == ''


def test_truncate_to_tokens_char_fallback_on_tokenizer_failure():
    from app.modules.assistant.llm_text import truncate_to_tokens, count_tokens

    class _BoomLLM:
        def tokenize(self, b):
            raise RuntimeError('model not loaded')

    llm = _BoomLLM()
    # count falls back to ~4 chars/token
    assert count_tokens(llm, 'x' * 40) == 10
    # truncate falls back to a char slice from the correct end (4 chars/token)
    text = 'HEAD' + 'm' * 32 + 'TAIL'  # 40 chars
    assert truncate_to_tokens(llm, text, 1, keep='head') == 'HEAD'
    assert truncate_to_tokens(llm, text, 1, keep='tail') == 'TAIL'


def test_llm_helpers_are_single_shared_impl():
    """assistant.memory, assistant.routes and deep_mind.analysis must all
    reference the one implementation, not private copies."""
    import warnings
    warnings.filterwarnings('ignore')
    from app.modules.assistant import llm_text, memory, routes
    from app.modules.deep_mind import analysis

    assert memory._strip_think is llm_text.strip_think
    assert routes._strip_think is llm_text.strip_think
    assert analysis._strip_think is llm_text.strip_think
    assert memory._count_tokens is llm_text.count_tokens
    assert routes._count_tokens is llm_text.count_tokens


# ── #11(b): shared system-stdlib finder (frozen-build path, now testable) ───

def _make_venv_cfg(venv_dir, home, version):
    venv_dir.mkdir(parents=True, exist_ok=True)
    (venv_dir / 'pyvenv.cfg').write_text(f'home = {home}\nversion = {version}\n')


def test_find_system_stdlib_unix_layout(tmp_path):
    import sys
    from paths import find_system_stdlib

    major, minor = sys.version_info.major, sys.version_info.minor
    base = tmp_path / 'pybase'
    (base / 'bin').mkdir(parents=True)
    stdlib = base / 'lib' / f'python{major}.{minor}'
    stdlib.mkdir(parents=True)
    (stdlib / 'os.py').write_text('# fake stdlib')

    venv = tmp_path / 'venv'
    _make_venv_cfg(venv, base / 'bin', f'{major}.{minor}.0')

    assert find_system_stdlib(venv) == stdlib


def test_find_system_stdlib_windows_layout(tmp_path):
    import sys
    from paths import find_system_stdlib

    major, minor = sys.version_info.major, sys.version_info.minor
    base = tmp_path / 'pybase'
    (base / 'Scripts').mkdir(parents=True)
    lib = base / 'Lib'
    lib.mkdir(parents=True)
    (lib / 'os.py').write_text('# fake stdlib')

    venv = tmp_path / 'venv'
    _make_venv_cfg(venv, base / 'Scripts', f'{major}.{minor}.0')

    assert find_system_stdlib(venv) == lib


def test_find_system_stdlib_rejects_version_mismatch(tmp_path):
    from paths import find_system_stdlib

    # A 2.7 venv must be refused even if a stdlib is present — cross-version
    # stdlib breaks C-extension imports.
    base = tmp_path / 'pybase'
    (base / 'Lib').mkdir(parents=True)
    (base / 'Lib' / 'os.py').write_text('x')
    venv = tmp_path / 'venv'
    _make_venv_cfg(venv, base, '2.7.18')

    assert find_system_stdlib(venv) is None


def test_find_system_stdlib_missing_or_unfindable(tmp_path):
    import sys
    from paths import find_system_stdlib

    # No pyvenv.cfg at all.
    assert find_system_stdlib(tmp_path / 'nope') is None

    # cfg present + matching version but no stdlib on disk → None, no raise.
    major, minor = sys.version_info.major, sys.version_info.minor
    venv = tmp_path / 'venv'
    _make_venv_cfg(venv, tmp_path / 'ghost' / 'bin', f'{major}.{minor}.0')
    assert find_system_stdlib(venv) is None


# ── #10: AI-psychologist tools split out of memory.py into tools.py ─────────

def test_tools_run_without_a_model(app):
    """The extracted tools are pure DB -> string lookups, so they run with no
    LLM loaded — which is exactly why moving them out of routes/memory is
    valuable: they became unit-testable. Also a smoke test that the split
    didn't break the imports the streaming path relies on."""
    from datetime import date, timedelta

    from app import db
    from app.models import MoodEntry
    from app.modules.assistant import tools

    today = date.today()
    for i, rating in enumerate([8, 4, 9, 6, 7]):
        db.session.add(MoodEntry(date=today - timedelta(days=i), rating=rating,
                                 note=f'day {i}', deleted=False))
    db.session.commit()

    assert 'Всего записей: 5' in tools.tool_diary_stats()
    assert 'Тренд настроения' in tools.tool_mood_trend(window_days=30)

    bw = tools.tool_best_worst_days(top_n=2)
    assert 'Лучшие дни' in bw and 'Худшие дни' in bw

    # A soft-deleted day must not leak into a tool's stats.
    db.session.add(MoodEntry(date=today - timedelta(days=10), rating=1,
                             note='deleted', deleted=True))
    db.session.commit()
    assert 'Всего записей: 5' in tools.tool_diary_stats()

    # Empty-diary path returns a graceful message, not a crash.
    MoodEntry.query.delete()
    db.session.commit()
    assert tools.tool_diary_stats() == 'В дневнике пока нет записей.'


def test_execute_tool_dispatch_still_wired(app):
    """routes._execute_tool now imports from .tools — verify the dispatch
    path resolves and returns a real tool result."""
    from datetime import date
    from app import db
    from app.models import MoodEntry
    from app.modules.assistant.routes import _execute_tool

    db.session.add(MoodEntry(date=date.today(), rating=7, note='hi', deleted=False))
    db.session.commit()

    out = _execute_tool('diary_stats', {})
    assert out and 'Статистика дневника' in out


# ── #2: the frozen-app log is rotated, not unbounded ───────────────────────

def test_log_handler_is_bounded_and_utf8(tmp_path):
    import logging.handlers
    from run import _make_rotating_handler, _LOG_MAX_BYTES, _LOG_BACKUP_COUNT

    handler = _make_rotating_handler(str(tmp_path / 'index-life.log'))
    try:
        # A RotatingFileHandler (not basicConfig's unbounded FileHandler).
        assert isinstance(handler, logging.handlers.RotatingFileHandler)
        assert handler.maxBytes == _LOG_MAX_BYTES > 0
        assert handler.backupCount == _LOG_BACKUP_COUNT >= 1
        # utf-8 so Russian log lines don't crash on a non-UTF-8 GUI locale.
        assert (handler.encoding or '').lower() in ('utf-8', 'utf8')
    finally:
        handler.close()


# ── #3: the embed subprocess respawns once if it dies mid-session ──────────

class _FakeStream:
    def __init__(self, lines=None):
        self._lines = list(lines or [])

    def write(self, _s):
        pass

    def flush(self):
        pass

    def readline(self):
        return self._lines.pop(0) if self._lines else ''


class _FakeProc:
    def __init__(self, responses, alive=True):
        self.stdin = _FakeStream()
        self.stdout = _FakeStream(responses)
        self.stderr = iter(())
        self._alive = alive
        self.pid = 4242

    def poll(self):
        return None if self._alive else 0

    def terminate(self):
        self._alive = False


def _bare_embedder(proc):
    """An embedder instance with internals set but no real subprocess."""
    import collections
    import threading
    from app.modules.assistant import memory

    emb = object.__new__(memory._SubprocessEmbedder)
    emb._lock = threading.Lock()
    emb._stderr_tail = collections.deque(maxlen=80)
    emb._venv_python = 'python3'
    emb._proc = proc
    return emb


def _ok_response(vec):
    import base64
    return json.dumps({
        'ok': True,
        'data': base64.b64encode(vec.tobytes()).decode('ascii'),
    }) + '\n'


def test_embed_worker_respawns_once_on_death():
    import numpy as np

    vec = np.ones(384, dtype=np.float32)
    dead = _FakeProc(responses=[''], alive=False)          # readline '' = exited
    fresh = _FakeProc(responses=[_ok_response(vec)], alive=True)

    emb = _bare_embedder(dead)
    spawned = {'n': 0}

    def fake_spawn():
        spawned['n'] += 1
        emb._proc = fresh

    emb._spawn = fake_spawn

    out = emb.encode('hello')
    assert spawned['n'] == 1                # respawned exactly once
    assert np.allclose(out, vec)            # the retry produced the vector


def test_embed_worker_does_not_respawn_on_model_error():
    import pytest

    proc = _FakeProc(responses=[json.dumps({'ok': False, 'error': 'boom'}) + '\n'])
    emb = _bare_embedder(proc)
    spawned = {'n': 0}
    emb._spawn = lambda: spawned.__setitem__('n', spawned['n'] + 1)

    with pytest.raises(RuntimeError):
        emb.encode('hi')
    assert spawned['n'] == 0                # model error must NOT respawn a live worker
