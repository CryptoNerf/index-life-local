# index.life — Local mood diary
# https://github.com/CryptoNerf/index-life-local
# Copyright (C) 2026 Émile Alexanyan
#
# Licensed under AGPL-3.0 with additional terms per Section 7
# (preservation of author attribution, no misrepresentation of
# origin). See LICENSE and COPYRIGHT at the root of this project.
"""
Multi-layer memory system for AI Psychologist.

Layer 1 (Raw):    Original MoodEntry records
Layer 2 (Vector): Embeddings + semantic search
Layer 3 (Summary): Per-entry summaries + monthly overviews
Layer 4 (Profile): Structured psychological profile (JSON)
"""
import base64
import collections
import hashlib
import json
import logging
import os
import re
import subprocess
import sys
import threading
from datetime import datetime
from app.timeutil import utcnow
from pathlib import Path

import numpy as np
from app import db
from app.models import (
    MoodEntry, EntrySummary, PeriodSummary,
    EntryEmbedding, UserPsychProfile, ChatMessage, EntryPerson, EntryActivity,
)
from .prompts import (
    SUMMARY_PROMPT, PROFILE_PROMPT, MONTH_SUMMARY_PROMPT, PEOPLE_PROMPT,
    ACTIVITIES_PROMPT,
    PROFILE_SECTION, TIMELINE_SECTION, RELEVANT_SECTION, RECENT_SECTION,
    SYSTEM_PROMPT, DIARY_ACCESS_PRESENT, DIARY_ACCESS_EMPTY,
)
from .llm_text import (
    strip_think as _strip_think,
    count_tokens as _count_tokens,
    truncate_to_tokens,
)

log = logging.getLogger(__name__)

# ── Embedding via subprocess ─────────────────────────────────────
# In frozen (PyInstaller) builds, sentence_transformers cannot be
# imported because transformers' _LazyModule conflicts with the
# FrozenImporter.  We run the embedding model in a persistent child
# process that uses the modules_venv Python — zero frozen-env issues.

_EMBED_WORKER_CODE = r'''
import sys, json, base64
import numpy as np
from sentence_transformers import SentenceTransformer

# Prefer the local cache so the model loads OFFLINE — no network HEAD checks
# to huggingface.co. Without internet those checks otherwise retry for ~30s
# and the whole reply appears to hang. Fall back to an online load only if
# the model isn't cached yet (the first run needs internet once).
_NAME = 'intfloat/multilingual-e5-small'
try:
    model = SentenceTransformer(_NAME, device='cpu', local_files_only=True)
except Exception:
    model = SentenceTransformer(_NAME, device='cpu')
sys.stdout.write('READY\n')
sys.stdout.flush()

for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    try:
        req = json.loads(line)
        vec = model.encode(req['text'], normalize_embeddings=True,
                           show_progress_bar=False)
        data = base64.b64encode(vec.astype(np.float32).tobytes()).decode()
        sys.stdout.write(json.dumps({'ok': True, 'data': data}) + '\n')
    except Exception as e:
        sys.stdout.write(json.dumps({'ok': False, 'error': str(e)}) + '\n')
    sys.stdout.flush()
'''


def _find_venv_python() -> Path:
    """Locate the modules_venv Python interpreter."""
    from app.modules import _get_user_data_dir
    base = _get_user_data_dir()
    venv = base / 'modules_venv'
    if sys.platform == 'win32':
        python = venv / 'Scripts' / 'python.exe'
    else:
        python = venv / 'bin' / 'python3'

    if not python.exists():
        raise FileNotFoundError(f'Venv Python not found: {python}')
    return python


class _SubprocessEmbedder:
    """Runs sentence-transformers in a child process (venv Python).

    Communication: one JSON line per request on stdin, one JSON line
    response on stdout.  The child stays alive for the app lifetime.
    """

    def __init__(self):
        venv_python = _find_venv_python()
        self._lock = threading.Lock()
        # Keep a rolling tail of the child's stderr for diagnostics.
        self._stderr_tail: 'collections.deque[str]' = collections.deque(maxlen=80)

        # Quiet the child so it writes little to stderr (the drain thread
        # below already prevents a full-pipe deadlock, but less noise is
        # cheaper and keeps logs readable).
        env = dict(os.environ)
        env.setdefault('HF_HUB_DISABLE_PROGRESS_BARS', '1')
        env.setdefault('TRANSFORMERS_VERBOSITY', 'error')
        env.setdefault('TOKENIZERS_PARALLELISM', 'false')
        # Force UTF-8 on both ends of the pipes. A GUI app launched from Finder
        # (macOS) or Explorer (Windows) often has a non-UTF-8 locale (ASCII /
        # ANSI codepage). Without forcing UTF-8, the parent's text-mode reads
        # raise UnicodeDecodeError on the child's non-ASCII stderr — which kills
        # the drain thread below and re-introduces the full-pipe deadlock that
        # freezes every encode (reindex/sync stall at "1/225 embedded"). The
        # module installer already does this; see app/module_routes.py.
        env['PYTHONIOENCODING'] = 'utf-8'
        env['PYTHONUTF8'] = '1'

        self._proc = subprocess.Popen(
            [str(venv_python), '-c', _EMBED_WORKER_CODE],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding='utf-8',
            errors='replace',
            bufsize=1,
            env=env,
        )

        # CRITICAL: continuously drain the child's stderr. sentence-transformers
        # / torch are chatty on stderr; if we never read it, the OS pipe buffer
        # (~64 KB) fills and the child blocks on its next stderr write — which
        # deadlocks every subsequent encode (parent waits forever on stdout).
        self._stderr_thread = threading.Thread(
            target=self._drain_stderr, daemon=True)
        self._stderr_thread.start()

        # Wait for model to load (may take 10-30s first time — downloads ~90 MB)
        ready = self._proc.stdout.readline().strip()
        if ready != 'READY':
            # Child likely exited; let the drain thread flush its stderr.
            self._stderr_thread.join(timeout=1.0)
            err = ''.join(self._stderr_tail)[-4000:]
            raise RuntimeError(f'Embed worker failed: {err}')
        log.info('Subprocess embedder started (pid=%d)', self._proc.pid)

    def _drain_stderr(self):
        """Read the child's stderr forever so its pipe never fills up."""
        try:
            for line in self._proc.stderr:
                self._stderr_tail.append(line)
        except Exception:
            pass

    def encode(self, text: str, normalize_embeddings: bool = True) -> np.ndarray:
        """Send text, get back float32 numpy vector."""
        with self._lock:
            req = json.dumps({'text': text}) + '\n'
            self._proc.stdin.write(req)
            self._proc.stdin.flush()
            resp_line = self._proc.stdout.readline()
            if not resp_line:
                raise RuntimeError('Embed worker died unexpectedly')
            resp = json.loads(resp_line)
        if not resp['ok']:
            raise RuntimeError(resp['error'])
        return np.frombuffer(base64.b64decode(resp['data']),
                             dtype=np.float32).copy()

    def close(self):
        if self._proc.poll() is None:
            self._proc.terminate()


_embed_model = None
_embed_lock = threading.Lock()


def _get_embed_model():
    """Lazy-load the embedding model (thread-safe).

    Frozen builds: persistent subprocess with venv Python.
    Dev builds: direct in-process SentenceTransformer.
    """
    global _embed_model
    if _embed_model is not None:
        return _embed_model
    with _embed_lock:
        if _embed_model is not None:
            return _embed_model

        if getattr(sys, 'frozen', False):
            _embed_model = _SubprocessEmbedder()
        else:
            from sentence_transformers import SentenceTransformer
            name = 'intfloat/multilingual-e5-small'
            try:
                # Prefer the local cache → loads offline, no network HEAD
                # checks (otherwise, with no internet, huggingface_hub retries
                # for ~30s and the reply hangs).
                _embed_model = SentenceTransformer(
                    name, device='cpu', local_files_only=True,
                )
            except Exception:
                # Not cached yet — allow a one-time online download.
                _embed_model = SentenceTransformer(name, device='cpu')
        log.info('Embedding model ready')
    return _embed_model


def embed_text(text: str) -> np.ndarray:
    """Create embedding for a text string."""
    model = _get_embed_model()
    return model.encode(f'passage: {text}', normalize_embeddings=True)


def embed_query(text: str) -> np.ndarray:
    """Create embedding for a search query."""
    model = _get_embed_model()
    return model.encode(f'query: {text}', normalize_embeddings=True)


# ── Emotional tone detection ────────────────────────────────────

_tone_anchors: dict[str, np.ndarray] | None = None

_TONE_TEXTS = {
    'distressed': 'Мне очень плохо, я не могу справиться, всё рушится, хочу плакать',
    'sad': 'Мне грустно, одиноко, тоскливо, ничего не радует',
    'anxious': 'Я тревожусь, волнуюсь, не могу успокоиться, страшно',
    'neutral': 'Обычный день, ничего особенного, всё нормально',
    'positive': 'Мне хорошо, радостно, доволен, отличное настроение',
}


def _get_tone_anchors() -> dict[str, np.ndarray]:
    global _tone_anchors
    if _tone_anchors is None:
        _tone_anchors = {k: embed_query(v) for k, v in _TONE_TEXTS.items()}
    return _tone_anchors


def detect_emotional_tone(text: str) -> tuple[str, float]:
    """Detect emotional tone of user message via cosine similarity to anchors.

    Returns (tone_label, confidence_score).
    """
    try:
        query_vec = embed_query(text)
        anchors = _get_tone_anchors()
        best_tone = 'neutral'
        best_score = -1.0
        for tone, anchor_vec in anchors.items():
            score = float(np.dot(query_vec, anchor_vec))
            if score > best_score:
                best_score = score
                best_tone = tone
        return best_tone, best_score
    except Exception:
        return 'neutral', 0.0


def _text_hash(text: str) -> str:
    return hashlib.md5(text.encode('utf-8')).hexdigest()


def _summary_invalid(text: str) -> bool:
    if not text:
        return True
    if '<think>' in text.lower():
        return True
    stripped = text.strip()
    if len(stripped) < 5:
        return True
    return False


def _get_llm_n_ctx(llm) -> int | None:
    """Return LLM context window size if available."""
    if llm is None:
        return None
    try:
        value = getattr(llm, 'n_ctx', None)
        if callable(value):
            return int(value())
        if isinstance(value, (int, float)):
            return int(value)
    except Exception:
        return None
    return None


# ── Layer 2: Embeddings ─────────────────────────────────────────

def update_embedding(entry: MoodEntry):
    """Create or update embedding for a single entry."""
    text = f'{entry.date.isoformat()} Настроение: {entry.rating}/10. {(entry.note or "").strip()}'
    h = _text_hash(text)

    existing = EntryEmbedding.query.filter_by(entry_id=entry.id).first()
    if existing and existing.text_hash == h:
        return  # unchanged

    # Capture primitives before releasing DB connection. embed_text can take
    # 5-30s (subprocess call or first-time model load) — holding the
    # connection across this window risks "database is locked" for any
    # concurrent writer.
    entry_id = entry.id
    has_existing = existing is not None
    db.session.remove()

    vec = embed_text(text)
    vec_bytes = vec.astype(np.float32).tobytes()

    # Re-query for write — old ORM object is detached after db.session.remove()
    existing = EntryEmbedding.query.filter_by(entry_id=entry_id).first() if has_existing else None
    if existing:
        existing.embedding = vec_bytes
        existing.text_hash = h
    else:
        db.session.add(EntryEmbedding(
            entry_id=entry_id,
            embedding=vec_bytes,
            text_hash=h,
        ))
    db.session.commit()
    # A write happened (new row OR in-place re-embed). Bump the generation
    # so the cached matrix below is rebuilt — a row count check alone misses
    # in-place updates, which left semantic search on a stale vector after
    # an entry was edited.
    _invalidate_embedding_cache()


_embedding_cache: tuple[list[int], np.ndarray] | None = None
_embedding_cache_count: int = 0
_embedding_cache_gen: int = -1
# Bumped on every embedding write (create or in-place update). The previous
# count-only invalidation missed edits that re-embedded an entry without
# changing the row count, so search kept using the stale vector until an
# add/delete changed the count.
_embedding_gen: int = 0


def _invalidate_embedding_cache() -> None:
    """Mark the cached embedding matrix stale after an embedding write."""
    global _embedding_gen
    _embedding_gen += 1


def _get_embedding_matrix() -> tuple[list[int], np.ndarray] | None:
    """Load and cache the embedding matrix.

    Rebuilt when either the row count changes (insert / bulk-delete) or the
    write generation advances (in-place re-embed of an edited entry).
    """
    global _embedding_cache, _embedding_cache_count, _embedding_cache_gen
    current_count = EntryEmbedding.query.count()
    if (_embedding_cache is not None
            and _embedding_cache_count == current_count
            and _embedding_cache_gen == _embedding_gen):
        return _embedding_cache
    all_embs = EntryEmbedding.query.all()
    if not all_embs:
        _embedding_cache = None
        _embedding_cache_count = 0
        _embedding_cache_gen = _embedding_gen
        return None
    entry_ids = [emb.entry_id for emb in all_embs]
    matrix = np.stack([np.frombuffer(emb.embedding, dtype=np.float32)
                       for emb in all_embs])
    _embedding_cache = (entry_ids, matrix)
    _embedding_cache_count = current_count
    _embedding_cache_gen = _embedding_gen
    return _embedding_cache


def search_relevant_entries(query: str, top_k: int = 5,
                            min_score: float = 0.35) -> list[MoodEntry]:
    """Find most semantically relevant entries for a query.

    Only returns entries with cosine similarity >= min_score to avoid
    polluting context with irrelevant noise. Uses cached embedding matrix.
    """
    query_vec = embed_query(query)

    cached = _get_embedding_matrix()
    if cached is None:
        return []
    entry_ids, matrix = cached

    # Vectorized cosine similarity
    scores = matrix @ query_vec
    top_indices = np.argsort(scores)[::-1][:top_k]

    # Filter by minimum similarity threshold
    result_ids = [entry_ids[i] for i in top_indices if scores[i] >= min_score]
    if not result_ids:
        return []

    entries = (MoodEntry.query
               .filter(MoodEntry.id.in_(result_ids), MoodEntry.deleted == False)
               .all())
    id_to_entry = {e.id: e for e in entries}
    return [id_to_entry[eid] for eid in result_ids if eid in id_to_entry]


# ── Layer 3: Summaries ──────────────────────────────────────────

def generate_entry_summary(entry: MoodEntry, llm) -> EntrySummary | None:
    """Generate a 1-2 sentence summary + themes for an entry using the LLM."""
    existing = EntrySummary.query.filter_by(entry_id=entry.id).first()
    if existing and not _summary_invalid(existing.summary):
        return existing

    # Capture primitives before releasing DB connection
    entry_id = entry.id
    entry_date = entry.date
    entry_rating = entry.rating
    note = (entry.note or '').strip()
    has_existing = existing is not None

    # Release DB connection before the LLM call (may take 5-30s)
    db.session.remove()

    if not note:
        summary_text = f'Настроение {entry_rating}/10, без заметки.'
        themes_list = []
    else:
        prompt = SUMMARY_PROMPT.format(
            date=entry_date.isoformat(),
            rating=entry_rating,
            note=note,
        )
        try:
            from .routes import _llm_inference_lock
            with _llm_inference_lock:
                result = llm.create_chat_completion(
                    messages=[{'role': 'user', 'content': prompt}],
                    max_tokens=320,
                    temperature=0.3,
                )
            response_text = result['choices'][0]['message']['content'].strip()
            summary_text, themes_list = _parse_summary_response(response_text)
        except Exception as e:
            log.warning(f'Failed to summarize entry {entry_id}: {e}')
            summary_text = note[:200] + ('...' if len(note) > 200 else '')
            themes_list = []
    summary_text = _strip_think(summary_text)
    if not summary_text:
        summary_text = note[:200] + ('...' if len(note) > 200 else '')
    if not summary_text:
        summary_text = f'Настроение {entry_rating}/10, без заметки.'

    # Re-query after db.session.remove() — old ORM object is detached
    existing = EntrySummary.query.filter_by(entry_id=entry_id).first() if has_existing else None

    if existing:
        existing.summary = summary_text
        existing.themes = json.dumps(themes_list, ensure_ascii=False)
        existing.created_at = utcnow()
        obj = existing
    else:
        obj = EntrySummary(
            entry_id=entry_id,
            summary=summary_text,
            themes=json.dumps(themes_list, ensure_ascii=False),
            created_at=utcnow(),
        )
        db.session.add(obj)
    db.session.commit()
    return obj


def _parse_summary_response(text: str) -> tuple[str, list[str]]:
    """Parse LLM response for entry summary."""
    text = _strip_think(text)
    summary = ''
    themes = []
    for line in text.split('\n'):
        line = line.strip()
        if line.upper().startswith('SUMMARY:'):
            summary = line[8:].strip()
        elif line.upper().startswith('THEMES:'):
            raw = line[7:].strip()
            themes = [t.strip() for t in raw.split(',') if t.strip()]
    if not summary:
        summary = text.split('\n')[0].strip()
    return summary, themes


_VALID_TONES = ('positive', 'neutral', 'negative')

# pymorphy3 is loaded lazily — first call to _to_nominative() creates the
# analyzer, then it's cached for the lifetime of the process. The library
# is not bundled in the frozen exe; it lives in modules_venv next to
# llama-cpp-python and is imported via the venv on sys.path. If the venv
# was built before we added pymorphy3 (older installs), the import fails
# and we fall back to no-op lemmatization (just capitalize first letter).
_morph_analyzer: object = None
_morph_load_attempted = False


def _get_morph_analyzer():
    global _morph_analyzer, _morph_load_attempted
    if _morph_load_attempted:
        return _morph_analyzer
    _morph_load_attempted = True
    try:
        import pymorphy3
        _morph_analyzer = pymorphy3.MorphAnalyzer()
        log.info('pymorphy3 analyzer loaded')
    except Exception as exc:
        log.warning(f'pymorphy3 not available — falling back to capitalize-only: {exc}')
        _morph_analyzer = None
    return _morph_analyzer


def _name_lemma(word: str) -> str | None:
    """Lemma for a Russian first/last name, in lowercase nominative
    singular — or None when pymorphy3 can't confidently tell that this
    word IS a name.

    The `Name` tag gate is what makes this safe to call on proper nouns:
    without it, pymorphy3 happily parses unfamiliar names as common
    nouns ("Мари" → "марь" as if it were a verbal adverb, "Дарёна" →
    "Дарёный" as if it were an adjective), which then collapses the
    chart into the wrong canonical form.

    Use this for the People-chart aggregation so "Дима" / "Димой" /
    "Димы" / "Диму" all merge to "Дима", while leaving unrecognised
    names untouched for the user to merge manually via aliases.
    """
    if not word or not word.strip():
        return None
    morph = _get_morph_analyzer()
    if morph is None:
        return None
    try:
        parses = morph.parse(word.lower())
    except Exception:
        return None
    # Collect every Name-tagged parse's nominative form, then pick the
    # LONGEST one. Pymorphy3 sometimes hallucinates a shorter masculine
    # reading of a feminine name when the cases collide (e.g. "Марусе"
    # → "марус" as if it were locative of a non-existent "Марус", same
    # rank as the correct "маруся"). The longer lemma preserves more of
    # the original word and is the right answer in those ties.
    candidates: list[str] = []
    for parse in parses[:5]:
        if 'Name' not in parse.tag:
            continue
        try:
            inflected = parse.inflect({'nomn'})
            if inflected and inflected.word:
                candidates.append(inflected.word)
                continue
        except Exception:
            pass
        if parse.normal_form:
            candidates.append(parse.normal_form)
    if not candidates:
        return None
    best = max(candidates, key=len)
    # Feminine-ending safeguard: when the original ends in а / я (the
    # canonical feminine markers) but the proposed lemma doesn't, that's
    # the "Поля → Поль" failure mode — pymorphy3 only carries a
    # masculine reading of the unfamiliar feminine name, so collapsing
    # to it would be a misgender. Better to bail and leave the form
    # alone for the user to alias.
    last = word.lower()[-1]
    if last in ('а', 'я') and best[-1] not in ('а', 'я'):
        return None
    return best


def _to_nominative(word: str) -> str:
    """Inflect a Russian common noun to its nominative case while keeping
    its number (singular vs plural).

    Only applied to lowercase single-word tokens (roles like "мама",
    "родителях", "коллегой"). Proper names and multi-word phrases are
    left untouched — pymorphy3 mangles rare/unknown names ("Дарёна"
    → "Дарёный"), and short feminine names like "Поля" overlap with
    masculine "Поль" with unstable score-ranking.

    Uses `parse.inflect({'nomn'})` rather than `normal_form` so that
    "родителях" → "родители" (plural preserved) instead of becoming
    singular "родитель". `normal_form` always lemmatizes to singular,
    which produces awkward role labels for collectives like "родители".
    """
    if not word or not word.strip():
        return word
    if ' ' in word:  # pymorphy3 is single-token; phrases pass through
        return word
    if word[0].isupper():  # proper noun
        return word
    morph = _get_morph_analyzer()
    if morph is None:
        return word
    try:
        parses = morph.parse(word)
    except Exception:
        return word
    if not parses:
        return word
    parse = parses[0]
    try:
        inflected = parse.inflect({'nomn'})
        if inflected and inflected.word:
            return inflected.word
    except Exception:
        pass
    return parse.normal_form or word


# Generic social roles that don't identify a specific person — multiple
# people in the user's life share these labels, so aggregating them on
# the chart says little. The user explicitly asked to drop friend-style
# roles (in contrast to specific-referent roles like мама/папа which
# typically refer to a single person).
_GENERIC_ROLE_BLACKLIST = {
    'друг', 'подруга', 'друзья', 'подруги', 'товарищ', 'товарищи',
    'приятель', 'приятельница', 'человек', 'люди',
}


# LLM occasionally extracts pronouns ("она", "он", "это") as "people". Drop
# them — they aren't real mentions of anyone identifiable.
_PRONOUN_BLACKLIST = {
    'он', 'она', 'оно', 'они', 'мы', 'вы', 'я', 'ты',
    'это', 'тот', 'та', 'те', 'этот', 'эта', 'эти',
    'кто', 'что', 'кто-то', 'что-то', 'кто-либо',
    'некто', 'нечто', 'все', 'всё',
}


def _is_pronoun_like(mention: str) -> bool:
    """True if the mention is a pronoun — should be excluded from people chart."""
    low = mention.strip().lower()
    if not low:
        return True
    if low in _PRONOUN_BLACKLIST:
        return True
    morph = _get_morph_analyzer()
    if morph is None:
        return False
    try:
        parses = morph.parse(low)
    except Exception:
        return False
    if not parses:
        return False
    # Drop only if every top parse agrees it's a pronoun (NPRO).
    top = parses[:3]
    return all('NPRO' in p.tag for p in top)


def _is_blacklisted(mention: str) -> bool:
    """True if mention should be dropped: pronoun or generic non-specific role.

    Used both at extraction time (to avoid writing junk to entry_people) and
    at chart aggregation time (so existing rows with these labels disappear
    from the chart without needing a re-extract).
    """
    if not mention or not mention.strip():
        return True
    if _is_pronoun_like(mention):
        return True
    # After lemmatization, generic roles end up in canonical lowercase form
    low = mention.strip().lower()
    if low in _GENERIC_ROLE_BLACKLIST:
        return True
    return False


def _normalize_mention(raw: str) -> str:
    """Lemmatize to nominative + capitalize first letter.

    Two lemmatisation paths:

    * Proper-noun path (capitalised single token) — uses `_name_lemma`,
      which only trusts pymorphy3's parse when it carries the `Name`
      tag. This catches "Димой" → "Дима", "Арману" → "Арман",
      "Марусе" → "Маруся" without mangling rare or foreign names
      ("Мари" / "Дарёна" stay as-is for manual alias merging).
    * Common-noun path — uses `_to_nominative` for role labels like
      "мама", "коллегой", "родителях".

    Compound names like "Анна-Мария" survive unchanged because both
    paths leave multi-word tokens alone, and we only touch the first
    letter.
    """
    s = raw.strip()
    if not s:
        return s
    if s[0].isupper() and ' ' not in s and '-' not in s:
        name_norm = _name_lemma(s)
        if name_norm:
            s = name_norm
        # Otherwise leave the form alone — better an un-merged duplicate
        # the user can alias than a wrong canonical form forced on them.
    else:
        lemma = _to_nominative(s)
        if lemma:
            s = lemma
    return s[0].upper() + s[1:]


def _parse_people_response(text: str) -> list[dict]:
    """Parse LLM people-extraction response into [{mention, tone}, ...]."""
    text = _strip_think(text)
    # Find the JSON array (LLM occasionally wraps it or adds preamble)
    start = text.find('[')
    end = text.rfind(']')
    if start == -1 or end == -1 or end < start:
        return []
    raw = text[start:end + 1]
    try:
        data = json.loads(raw)
    except Exception:
        return []
    if not isinstance(data, list):
        return []

    result = []
    seen = set()
    for item in data:
        if not isinstance(item, dict):
            continue
        raw = str(item.get('mention') or item.get('name') or '').strip()
        mention = _normalize_mention(raw)
        if _is_blacklisted(mention):
            continue
        tone = str(item.get('tone') or '').strip().lower()
        if not mention or len(mention) > 100:
            continue
        if tone not in _VALID_TONES:
            continue
        # Dedupe within a single entry — LLM occasionally repeats mentions
        key = (mention.lower(), tone)
        if key in seen:
            continue
        seen.add(key)
        result.append({'mention': mention, 'tone': tone})
    return result


def extract_people_mentions(entry: MoodEntry, llm) -> list[EntryPerson]:
    """Extract person/role mentions for `entry` via LLM, replacing prior rows.

    Idempotent on re-runs — deletes the entry's existing mentions first, so
    editing an entry cleanly updates the extracted data.
    """
    # Capture primitives before any DB operations
    entry_id = entry.id
    entry_date = entry.date
    entry_rating = entry.rating
    note = (entry.note or '').strip()

    # DELETE in its own short transaction, then release the connection before
    # the LLM call — otherwise SQLite holds the write lock for the entire
    # 5-30s LLM latency and concurrent writers hit "database is locked".
    EntryPerson.query.filter_by(entry_id=entry_id).delete()
    db.session.commit()
    db.session.remove()  # release connection before LLM

    if not note:
        return []

    prompt = PEOPLE_PROMPT.format(
        date=entry_date.isoformat(),
        rating=entry_rating,
        note=note,
    )
    try:
        from .routes import _llm_inference_lock
        with _llm_inference_lock:
            result = llm.create_chat_completion(
                messages=[{'role': 'user', 'content': prompt}],
                max_tokens=400,
                temperature=0.2,
            )
        response_text = result['choices'][0]['message']['content'].strip()
        mentions = _parse_people_response(response_text)
    except Exception as e:
        log.warning(f'Failed to extract people from entry {entry_id}: {e}')
        return []

    objs = []
    for m in mentions:
        obj = EntryPerson(entry_id=entry_id, mention=m['mention'], tone=m['tone'])
        db.session.add(obj)
        objs.append(obj)
    db.session.commit()
    return objs


def _parse_activities_response(text: str) -> list[str]:
    """Parse LLM activities-extraction response into a list of canonical labels."""
    text = _strip_think(text)
    start = text.find('[')
    end = text.rfind(']')
    if start == -1 or end == -1 or end < start:
        return []
    raw = text[start:end + 1]
    try:
        data = json.loads(raw)
    except Exception:
        return []
    if not isinstance(data, list):
        return []

    result = []
    seen = set()
    for item in data:
        if isinstance(item, dict):
            label = item.get('activity') or item.get('name') or ''
        elif isinstance(item, str):
            label = item
        else:
            continue
        label = str(label).strip().lower()
        if not label or len(label) > 30:
            continue
        if label in seen:
            continue
        seen.add(label)
        result.append(label)
        if len(result) >= 5:
            break
    return result


def extract_activities(entry: MoodEntry, llm) -> list[EntryActivity]:
    """Extract activity labels for `entry` via LLM, replacing prior rows.

    Idempotent — deletes the entry's existing rows first so re-runs on an
    edited entry produce a clean state.
    """
    # Capture primitives before any DB operations
    entry_id = entry.id
    entry_date = entry.date
    entry_rating = entry.rating
    note = (entry.note or '').strip()

    # See extract_people_mentions: commit DELETE then release connection before
    # LLM call so the write lock isn't held during the multi-second LLM latency.
    EntryActivity.query.filter_by(entry_id=entry_id).delete()
    db.session.commit()
    db.session.remove()  # release connection before LLM

    if not note:
        return []

    prompt = ACTIVITIES_PROMPT.format(
        date=entry_date.isoformat(),
        rating=entry_rating,
        note=note,
    )
    try:
        from .routes import _llm_inference_lock
        with _llm_inference_lock:
            result = llm.create_chat_completion(
                messages=[{'role': 'user', 'content': prompt}],
                max_tokens=200,
                temperature=0.2,
            )
        response_text = result['choices'][0]['message']['content'].strip()
        activities = _parse_activities_response(response_text)
    except Exception as e:
        log.warning(f'Failed to extract activities from entry {entry_id}: {e}')
        return []

    objs = []
    for a in activities:
        obj = EntryActivity(entry_id=entry_id, activity=a)
        db.session.add(obj)
        objs.append(obj)
    db.session.commit()
    return objs


def generate_month_summary(year: int, month: int, llm) -> PeriodSummary | None:
    """Generate or update a monthly summary."""
    period_key = f'{year:04d}-{month:02d}'

    entries = (MoodEntry.query
               .filter(db.extract('year', MoodEntry.date) == year)
               .filter(db.extract('month', MoodEntry.date) == month)
               .order_by(MoodEntry.date)
               .all())
    if not entries:
        return None

    # Check if summary exists and is up to date
    existing = PeriodSummary.query.filter_by(period_key=period_key).first()
    if existing and existing.entry_count == len(entries) and not _summary_invalid(existing.summary):
        return existing

    avg = sum(e.rating for e in entries) / len(entries)

    # Build entries text from summaries (prefer) or raw notes
    lines = []
    for e in entries:
        s = EntrySummary.query.filter_by(entry_id=e.id).first()
        if s:
            safe_summary = _strip_think(s.summary or '')
            lines.append(f'[{e.date.isoformat()}] {e.rating}/10. {safe_summary}')
        else:
            note = (e.note or '').strip()[:300]
            lines.append(f'[{e.date.isoformat()}] {e.rating}/10. {note}')
    entries_text = '\n'.join(lines)

    month_names = [
        '', 'январь', 'февраль', 'март', 'апрель', 'май', 'июнь',
        'июль', 'август', 'сентябрь', 'октябрь', 'ноябрь', 'декабрь'
    ]
    month_label = f'{month_names[month]} {year}'

    # Capture remaining primitives and release DB before LLM call
    n_entries = len(entries)
    has_existing = existing is not None
    db.session.remove()  # release connection before LLM

    try:
        prompt = MONTH_SUMMARY_PROMPT.format(
            month_label=month_label,
            entries_text=entries_text,
        )
        from .routes import _llm_inference_lock
        with _llm_inference_lock:
            result = llm.create_chat_completion(
                messages=[{'role': 'user', 'content': prompt}],
                max_tokens=384,
                temperature=0.3,
            )
        summary_text = result['choices'][0]['message']['content'].strip()
    except Exception as e:
        log.warning(f'Failed to generate month summary for {period_key}: {e}')
        summary_text = f'{n_entries} записей, средний рейтинг {avg:.1f}/10.'

    summary_text = _strip_think(summary_text)
    if not summary_text:
        summary_text = f'{n_entries} записей, средний рейтинг {avg:.1f}/10.'

    # Re-query after db.session.remove() — old ORM object is detached
    existing = PeriodSummary.query.filter_by(period_key=period_key).first() if has_existing else None

    if existing:
        existing.summary = summary_text
        existing.avg_rating = round(avg, 1)
        existing.entry_count = n_entries
        existing.created_at = utcnow()
    else:
        db.session.add(PeriodSummary(
            period_type='month',
            period_key=period_key,
            summary=summary_text,
            avg_rating=round(avg, 1),
            entry_count=n_entries,
            created_at=utcnow(),
        ))
    db.session.commit()
    return PeriodSummary.query.filter_by(period_key=period_key).first()


# ── Layer 4: Profile ────────────────────────────────────────────

def update_profile(llm, force_rebuild: bool = False):
    """Generate or update the psychological profile."""
    profile = UserPsychProfile.query.first()
    total_entries = MoodEntry.query.count()

    if not total_entries:
        return profile

    # Rebuild every 50 entries or if forced
    needs_rebuild = (
        force_rebuild
        or profile is None
        or profile.entries_analyzed == 0
        or (total_entries - profile.entries_analyzed) >= 50
    )

    # Incremental update every 5 new entries
    needs_update = (
        profile is not None
        and not needs_rebuild
        and (total_entries - profile.entries_analyzed) >= 5
    )

    if not needs_rebuild and not needs_update:
        return profile

    # Gather all entry summaries
    summaries = (db.session.query(EntrySummary, MoodEntry)
                 .join(MoodEntry, EntrySummary.entry_id == MoodEntry.id)
                 .order_by(MoodEntry.date)
                 .all())

    if not summaries:
        return profile

    lines = []
    for s, e in summaries:
        themes = json.loads(s.themes) if s.themes else []
        themes_str = ', '.join(themes)
        safe_summary = _strip_think(s.summary or '')
        lines.append(f'[{e.date.isoformat()}] {e.rating}/10. {safe_summary} Темы: {themes_str}')
    summaries_text = '\n'.join(lines)

    # All data captured as primitives — release DB before the very long LLM call
    db.session.remove()

    # Token-aware truncation to fit model context window
    try:
        import os
        n_ctx = _get_llm_n_ctx(llm)
        if not n_ctx:
            raw_ctx = os.environ.get('LLM_N_CTX') or os.environ.get('LLM_CPU_N_CTX')
            n_ctx = int(raw_ctx) if raw_ctx else 4096
        # Larger safety because chat template adds hidden tokens
        safety = int(os.environ.get('LLM_PROFILE_PROMPT_SAFETY', '2048'))
        min_output = int(os.environ.get('LLM_PROFILE_MIN_OUTPUT', '256'))
        summary_cap = int(os.environ.get('LLM_PROFILE_SUMMARY_TOKEN_LIMIT', '2048'))
        base_prompt = PROFILE_PROMPT.format(summaries_text='')
        base_tokens = _count_tokens(llm, base_prompt)
        if summary_cap > 0:
            # keep='tail' — retain the most recent summaries when trimming.
            summaries_text = truncate_to_tokens(llm, summaries_text, summary_cap, keep='tail')
        # Ensure we leave room for a minimum output + safety.
        available_for_prompt = max(0, int(n_ctx) - safety - min_output)
        available_for_summaries = max(0, available_for_prompt - base_tokens)
        if available_for_summaries > 0:
            summaries_text = truncate_to_tokens(llm, summaries_text, available_for_summaries, keep='tail')
        # Final guard: ensure full prompt fits with min output budget.
        limit = max(0, int(n_ctx) - safety - min_output)
        for _ in range(3):
            prompt = PROFILE_PROMPT.format(summaries_text=summaries_text)
            prompt_tokens = _count_tokens(llm, prompt)
            if prompt_tokens <= limit:
                break
            summ_tokens = _count_tokens(llm, summaries_text)
            if summ_tokens <= 0:
                summaries_text = ''
                break
            # Reduce summaries more aggressively to avoid decode failures.
            new_limit = max(0, int(summ_tokens * 0.7))
            summaries_text = truncate_to_tokens(llm, summaries_text, new_limit, keep='tail')
    except Exception:
        # Fallback to rough char trimming
        if len(summaries_text) > 16000:
            summaries_text = summaries_text[-16000:]

    try:
        prompt = PROFILE_PROMPT.format(summaries_text=summaries_text)
        prompt_tokens = _count_tokens(llm, prompt)
        n_ctx = _get_llm_n_ctx(llm) or 4096
        safety = int(os.environ.get('LLM_PROFILE_PROMPT_SAFETY', '2048'))
        max_out = max(32, int(n_ctx) - prompt_tokens - safety)
        from .routes import _llm_inference_lock
        with _llm_inference_lock:
            result = llm.create_chat_completion(
                messages=[{'role': 'user', 'content': prompt}],
                max_tokens=min(2048, max_out),
                temperature=0.2,
            )
        raw = result['choices'][0]['message']['content'].strip()
        raw = _strip_think(raw)
        # Extract JSON from response
        profile_data = _extract_json(raw)
    except Exception as e:
        log.warning(f'Failed to generate profile: {e}')
        return None  # profile object is detached after db.session.remove()

    # Re-query after db.session.remove() — old ORM object is detached
    profile = UserPsychProfile.query.first()

    if profile is None:
        profile = UserPsychProfile(
            profile_json=json.dumps(profile_data, ensure_ascii=False, indent=2),
            version=1,
            entries_analyzed=total_entries,
            updated_at=utcnow(),
        )
        db.session.add(profile)
    else:
        profile.profile_json = json.dumps(profile_data, ensure_ascii=False, indent=2)
        profile.version += 1
        profile.entries_analyzed = total_entries
        profile.updated_at = utcnow()

    db.session.commit()
    return profile


def _extract_json(text: str) -> dict:
    """Extract JSON object from LLM response text, with regex fallback."""
    # Try direct parse
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # Try to find JSON block
    start = text.find('{')
    end = text.rfind('}')
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(text[start:end + 1])
        except json.JSONDecodeError:
            pass
    # Fallback: extract individual fields via regex
    result = {}
    for field in ('avg_rating', 'trend', 'risk_flags'):
        m = re.search(rf'"{field}"\s*:\s*"?([^",\}}]+)"?', text)
        if m:
            val = m.group(1).strip()
            if field == 'avg_rating':
                try:
                    result[field] = float(val)
                except ValueError:
                    pass
            else:
                result[field] = val
    for field in ('main_themes', 'negative_triggers', 'positive_triggers',
                  'coping', 'strengths', 'growth_areas', 'key_people'):
        m = re.search(rf'"{field}"\s*:\s*\[(.*?)\]', text, re.DOTALL)
        if m:
            items = re.findall(r'"([^"]+)"', m.group(1))
            result[field] = items
    if result:
        log.info('Profile JSON fallback extracted %d fields', len(result))
    return result


# ── Context assembly ────────────────────────────────────────────

_GREETING_WORDS = {
    'привет', 'здравствуй', 'здравствуйте', 'добрый', 'здарова',
    'хай', 'хей', 'hello', 'hi', 'hey', 'приветик', 'салют', 'йо',
}


def _is_light_message(text: str) -> bool:
    """Detect greetings and very short messages that don't need full context."""
    words = text.lower().split()
    if len(words) > 5:
        return False
    return any(w.rstrip('!.,') in _GREETING_WORDS for w in words)


_MONTHS_RU = {
    'января': 1, 'февраля': 2, 'марта': 3, 'апреля': 4,
    'мая': 5, 'июня': 6, 'июля': 7, 'августа': 8,
    'сентября': 9, 'октября': 10, 'ноября': 11, 'декабря': 12,
    'январь': 1, 'февраль': 2, 'март': 3, 'апрель': 4,
    'май': 5, 'июнь': 6, 'июль': 7, 'август': 8,
    'сентябрь': 9, 'октябрь': 10, 'ноябрь': 11, 'декабрь': 12,
}

_ORDINALS_RU = {
    'первого': 1, 'второго': 2, 'третьего': 3, 'четвёртого': 4,
    'четвертого': 4, 'пятого': 5, 'шестого': 6, 'седьмого': 7,
    'восьмого': 8, 'девятого': 9, 'десятого': 10,
    'одиннадцатого': 11, 'двенадцатого': 12, 'тринадцатого': 13,
    'четырнадцатого': 14, 'пятнадцатого': 15, 'шестнадцатого': 16,
    'семнадцатого': 17, 'восемнадцатого': 18, 'девятнадцатого': 19,
    'двадцатого': 20, 'двадцать первого': 21, 'двадцать второго': 22,
    'двадцать третьего': 23, 'двадцать четвёртого': 24,
    'двадцать четвертого': 24, 'двадцать пятого': 25,
    'двадцать шестого': 26, 'двадцать седьмого': 27,
    'двадцать восьмого': 28, 'двадцать девятого': 29,
    'тридцатого': 30, 'тридцать первого': 31,
}


def _extract_date_entries(text: str) -> list:
    """Extract diary entries whose dates are mentioned in any format.

    Supported:
      - 2026-02-09  (ISO)
      - 09.02.2026  (DD.MM.YYYY)
      - 9 февраля 2026 / 9 февраля  (numeric day + Russian month)
      - двенадцатого августа 2025 / двенадцатого августа  (ordinal + month)
    """
    from datetime import date as date_type
    dates_found: list[date_type] = []

    # 1) ISO: 2026-02-09
    for m in re.finditer(r'\b(\d{4})-(\d{2})-(\d{2})\b', text):
        try:
            dates_found.append(date_type(int(m[1]), int(m[2]), int(m[3])))
        except ValueError:
            pass

    # 2) DD.MM.YYYY
    for m in re.finditer(r'\b(\d{1,2})\.(\d{2})\.(\d{4})\b', text):
        try:
            dates_found.append(date_type(int(m[3]), int(m[2]), int(m[1])))
        except ValueError:
            pass

    # 3) "9 февраля 2026" or "9 февраля" (without year → current year)
    month_names = '|'.join(_MONTHS_RU.keys())
    for m in re.finditer(
        rf'\b(\d{{1,2}})\s+({month_names})(?:\s+(\d{{4}}))?', text, re.IGNORECASE
    ):
        day = int(m[1])
        month = _MONTHS_RU.get(m[2].lower())
        year = int(m[3]) if m[3] else datetime.now().year
        if month:
            try:
                dates_found.append(date_type(year, month, day))
            except ValueError:
                pass

    # 4) "двенадцатого августа 2025" or "двенадцатого августа"
    #    Handle compound ordinals like "двадцать первого"
    ordinal_names = '|'.join(sorted(_ORDINALS_RU.keys(), key=len, reverse=True))
    for m in re.finditer(
        rf'\b({ordinal_names})\s+({month_names})(?:\s+(\d{{4}}))?',
        text, re.IGNORECASE
    ):
        day = _ORDINALS_RU.get(m[1].lower())
        month = _MONTHS_RU.get(m[2].lower())
        year = int(m[3]) if m[3] else datetime.now().year
        if day and month:
            try:
                dates_found.append(date_type(year, month, day))
            except ValueError:
                pass

    if not dates_found:
        return []

    # Deduplicate and query
    unique_dates = list(dict.fromkeys(dates_found))
    entries = []
    for d in unique_dates:
        found = MoodEntry.query.filter_by(date=d, deleted=False).all()
        entries.extend(found)
    return entries


def _estimate_tokens(text: str) -> int:
    """Rough token estimate for Russian text (~2.5 chars per token)."""
    return max(1, len(text) * 10 // 25)


def assemble_context(user_message: str, max_system_tokens: int = 0) -> str:
    """Build the full system prompt from all 4 memory layers.

    For short greetings, reduces context to avoid overwhelming responses.
    If max_system_tokens > 0, truncate sections to fit the budget.
    """
    light = _is_light_message(user_message)

    # Layer 4: Profile (always include — background knowledge)
    profile = UserPsychProfile.query.first()
    if profile and profile.profile_json and profile.profile_json != '{}':
        profile_section = PROFILE_SECTION.format(profile_text=profile.profile_json)
    else:
        profile_section = ''

    # Layer 3: Monthly timeline (always include — lightweight)
    period_summaries = (PeriodSummary.query
                        .filter_by(period_type='month')
                        .order_by(PeriodSummary.period_key)
                        .all())
    if period_summaries:
        timeline_lines = []
        for ps in period_summaries:
            safe_summary = _strip_think(ps.summary or '')
            timeline_lines.append(
                f'{ps.period_key} (avg {ps.avg_rating}/10, {ps.entry_count} entries): {safe_summary}'
            )
        timeline_section = TIMELINE_SECTION.format(
            timeline_text='\n'.join(timeline_lines)
        )
    else:
        timeline_section = ''

    # Layer 2: Relevant entries via semantic search + date extraction
    # Skip for greetings — search on "привет" returns noise
    if light:
        relevant_section = ''
    else:
        try:
            relevant_entries = search_relevant_entries(user_message, top_k=5)
        except Exception as exc:
            log.warning(f'Vector search failed: {exc}')
            relevant_entries = []

        # Extract dates from current message AND recent USER messages
        # Only scan user messages to avoid bloating context with every date
        # the assistant mentioned in its analysis.
        date_entries = _extract_date_entries(user_message)
        if not date_entries:
            recent_user_msgs = (ChatMessage.query
                                .filter_by(role='user')
                                .order_by(ChatMessage.created_at.desc())
                                .limit(4).all())
            seen_ids = set()
            date_entries = []
            for msg in recent_user_msgs:
                found = _extract_date_entries(msg.content or '')
                for entry in found:
                    if entry.id not in seen_ids:
                        seen_ids.add(entry.id)
                        date_entries.append(entry)

        # Include ±1 day entries for context continuity
        if date_entries:
            from datetime import timedelta
            extra_dates = set()
            for entry in date_entries:
                extra_dates.add(entry.date - timedelta(days=1))
                extra_dates.add(entry.date + timedelta(days=1))
            for d in extra_dates:
                found = MoodEntry.query.filter_by(date=d, deleted=False).all()
                date_entries.extend(found)
            log.info('Date extraction found %d entries (with neighbors): %s',
                     len(date_entries),
                     list(set(ent.date.isoformat() for ent in date_entries)))
        else:
            log.info('Date extraction found no entries for message: %s', user_message[:100])

        # Merge: date entries first (full text), then semantic (truncated)
        date_ids = set(entry.id for entry in date_entries)
        seen_ids = set()
        all_relevant = []
        for entry in date_entries:
            if entry.id not in seen_ids:
                seen_ids.add(entry.id)
                all_relevant.append(entry)
        for entry in (relevant_entries or []):
            if entry.id not in seen_ids:
                seen_ids.add(entry.id)
                all_relevant.append(entry)

        if all_relevant:
            rel_lines = []
            max_semantic_chars = 400
            for entry in all_relevant:
                note = (entry.note or '').strip().replace('\n', ' ')
                # Date-extracted entries get full text; semantic results truncated
                if entry.id not in date_ids and len(note) > max_semantic_chars:
                    note = note[:max_semantic_chars] + '...'
                rel_lines.append(f'[{entry.date.isoformat()}] {entry.rating}/10. {note}')
            relevant_section = RELEVANT_SECTION.format(
                entries_text='\n'.join(rel_lines)
            )
            log.info('Relevant section: %d entries (%d by date, %d semantic), dates: %s',
                     len(rel_lines), len(date_ids),
                     len(rel_lines) - len(date_ids),
                     [entry.date.isoformat() for entry in all_relevant])
        else:
            relevant_section = ''

    # Layer 1: Recent raw entries (1 for greetings, 3 normally).
    # Exclude soft-deleted entries so the model never cites a deleted day.
    recent_limit = 1 if light else 3
    recent = (MoodEntry.query
              .filter_by(deleted=False)
              .order_by(MoodEntry.date.desc())
              .limit(recent_limit).all())
    if recent:
        rec_lines = []
        for e in recent:
            note = (e.note or '').strip()
            rec_lines.append(f'[{e.date.isoformat()}] {e.rating}/10. {note}')
        recent_section = RECENT_SECTION.format(entries_text='\n'.join(rec_lines))
    else:
        recent_section = ''

    # Choose the diary-access framing by whether the diary actually holds
    # data. If it's empty, telling the model "entries are below" makes it
    # invent entries — so swap in an explicit empty-diary instruction.
    has_diary_data = bool(
        profile_section or timeline_section or relevant_section or recent_section
    )
    if not has_diary_data:
        has_diary_data = MoodEntry.query.filter_by(deleted=False).count() > 0
    diary_access_section = (
        DIARY_ACCESS_PRESENT if has_diary_data else DIARY_ACCESS_EMPTY
    )

    today_str = datetime.now().strftime('%Y-%m-%d')
    full_text = SYSTEM_PROMPT.format(
        today=today_str,
        diary_access_section=diary_access_section,
        profile_section=profile_section,
        timeline_section=timeline_section,
        relevant_section=relevant_section,
        recent_section=recent_section,
    )

    # Truncate sections if system prompt exceeds token budget
    if max_system_tokens > 0:
        est = _estimate_tokens(full_text)
        if est > max_system_tokens:
            log.info('System prompt ~%d tokens exceeds budget %d, trimming',
                     est, max_system_tokens)
            # Priority: drop relevant → trim timeline → trim profile
            if relevant_section and _estimate_tokens(relevant_section) > 200:
                # Keep only first 3 entries
                lines = relevant_section.split('\n')
                relevant_section = '\n'.join(lines[:4])  # header + 3 entries
                full_text = SYSTEM_PROMPT.format(
                    today=today_str,
                    diary_access_section=diary_access_section,
                    profile_section=profile_section,
                    timeline_section=timeline_section,
                    relevant_section=relevant_section,
                    recent_section=recent_section,
                )
            est = _estimate_tokens(full_text)
            if est > max_system_tokens and timeline_section:
                # Keep only last 3 months
                lines = timeline_section.split('\n')
                timeline_section = '\n'.join(lines[:1] + lines[-3:])
                full_text = SYSTEM_PROMPT.format(
                    today=today_str,
                    diary_access_section=diary_access_section,
                    profile_section=profile_section,
                    timeline_section=timeline_section,
                    relevant_section=relevant_section,
                    recent_section=recent_section,
                )

    return full_text
