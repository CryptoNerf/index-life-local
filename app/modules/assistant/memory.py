"""
Multi-layer memory system for AI Psychologist.

Layer 1 (Raw):    Original MoodEntry records
Layer 2 (Vector): Embeddings + semantic search
Layer 3 (Summary): Per-entry summaries + monthly overviews
Layer 4 (Profile): Structured psychological profile (JSON)
"""
import hashlib
import json
import logging
import re
from datetime import datetime

import numpy as np
from app import db
from app.models import (
    MoodEntry, EntrySummary, PeriodSummary,
    EntryEmbedding, UserPsychProfile, ChatMessage,
)
from .prompts import (
    SUMMARY_PROMPT, PROFILE_PROMPT, MONTH_SUMMARY_PROMPT,
    PROFILE_SECTION, TIMELINE_SECTION, RELEVANT_SECTION, RECENT_SECTION,
    SYSTEM_PROMPT,
)

log = logging.getLogger(__name__)

# ── Embedding model (lazy-loaded) ───────────────────────────────

_embed_model = None


def _get_embed_model():
    """Lazy-load the sentence-transformers model."""
    global _embed_model
    if _embed_model is None:
        from sentence_transformers import SentenceTransformer
        _embed_model = SentenceTransformer(
            'intfloat/multilingual-e5-small',
            device='cpu',
        )
        log.info('Embedding model loaded: multilingual-e5-small')
    return _embed_model


def embed_text(text: str) -> np.ndarray:
    """Create embedding for a text string."""
    model = _get_embed_model()
    # multilingual-e5 expects "query: " or "passage: " prefix
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


def _strip_think(text: str) -> str:
    if not text:
        return ''
    # Remove any <think>...</think> blocks (case-insensitive).
    cleaned = re.sub(r'(?is)<think>.*?</think>', '', text)
    # Remove any trailing unclosed <think> block.
    cleaned = re.sub(r'(?is)<think>.*$', '', cleaned)
    # Remove stray closing tags.
    cleaned = re.sub(r'(?is)</think>', '', cleaned)
    return cleaned.strip()


def _summary_invalid(text: str) -> bool:
    if not text:
        return True
    if '<think>' in text.lower():
        return True
    stripped = text.strip()
    if len(stripped) < 5:
        return True
    return False


def _count_tokens(llm, text: str) -> int:
    try:
        tokens = llm.tokenize(text.encode('utf-8'))
        return len(tokens)
    except Exception:
        return max(1, len(text) // 4)


def _truncate_to_tokens(llm, text: str, max_tokens: int) -> str:
    if max_tokens <= 0:
        return ''
    try:
        tokens = llm.tokenize(text.encode('utf-8'))
        if len(tokens) <= max_tokens:
            return text
        truncated = llm.detokenize(tokens[-max_tokens:])
        if isinstance(truncated, bytes):
            return truncated.decode('utf-8', errors='ignore')
        if isinstance(truncated, str):
            return truncated
    except Exception:
        pass
    approx_chars = max(0, max_tokens * 4)
    return text[-approx_chars:]


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

    vec = embed_text(text)
    vec_bytes = vec.astype(np.float32).tobytes()

    if existing:
        existing.embedding = vec_bytes
        existing.text_hash = h
    else:
        db.session.add(EntryEmbedding(
            entry_id=entry.id,
            embedding=vec_bytes,
            text_hash=h,
        ))
    db.session.commit()


_embedding_cache: tuple[list[int], np.ndarray] | None = None
_embedding_cache_count: int = 0


def _get_embedding_matrix() -> tuple[list[int], np.ndarray] | None:
    """Load and cache the embedding matrix. Invalidates on count change."""
    global _embedding_cache, _embedding_cache_count
    current_count = EntryEmbedding.query.count()
    if _embedding_cache is not None and _embedding_cache_count == current_count:
        return _embedding_cache
    all_embs = EntryEmbedding.query.all()
    if not all_embs:
        _embedding_cache = None
        _embedding_cache_count = 0
        return None
    entry_ids = [emb.entry_id for emb in all_embs]
    matrix = np.stack([np.frombuffer(emb.embedding, dtype=np.float32)
                       for emb in all_embs])
    _embedding_cache = (entry_ids, matrix)
    _embedding_cache_count = current_count
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

    entries = MoodEntry.query.filter(MoodEntry.id.in_(result_ids)).all()
    id_to_entry = {e.id: e for e in entries}
    return [id_to_entry[eid] for eid in result_ids if eid in id_to_entry]


# ── Layer 3: Summaries ──────────────────────────────────────────

def generate_entry_summary(entry: MoodEntry, llm) -> EntrySummary | None:
    """Generate a 1-2 sentence summary + themes for an entry using the LLM."""
    existing = EntrySummary.query.filter_by(entry_id=entry.id).first()
    if existing and not _summary_invalid(existing.summary):
        return existing

    note = (entry.note or '').strip()
    if not note:
        summary_text = f'Настроение {entry.rating}/10, без заметки.'
        themes_list = []
    else:
        prompt = SUMMARY_PROMPT.format(
            date=entry.date.isoformat(),
            rating=entry.rating,
            note=note,
        )
        try:
            result = llm.create_chat_completion(
                messages=[{'role': 'user', 'content': prompt}],
                max_tokens=320,
                temperature=0.3,
            )
            response_text = result['choices'][0]['message']['content'].strip()
            summary_text, themes_list = _parse_summary_response(response_text)
        except Exception as e:
            log.warning(f'Failed to summarize entry {entry.id}: {e}')
            summary_text = note[:200] + ('...' if len(note) > 200 else '')
            themes_list = []
    summary_text = _strip_think(summary_text)
    if not summary_text:
        note_text = (entry.note or '').strip()
        summary_text = note_text[:200] + ('...' if len(note_text) > 200 else '')
    if not summary_text:
        summary_text = f'Настроение {entry.rating}/10, без заметки.'

    if existing:
        existing.summary = summary_text
        existing.themes = json.dumps(themes_list, ensure_ascii=False)
        existing.created_at = datetime.utcnow()
        obj = existing
    else:
        obj = EntrySummary(
            entry_id=entry.id,
            summary=summary_text,
            themes=json.dumps(themes_list, ensure_ascii=False),
            created_at=datetime.utcnow(),
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

    try:
        prompt = MONTH_SUMMARY_PROMPT.format(
            month_label=month_label,
            entries_text=entries_text,
        )
        result = llm.create_chat_completion(
            messages=[{'role': 'user', 'content': prompt}],
            max_tokens=384,
            temperature=0.3,
        )
        summary_text = result['choices'][0]['message']['content'].strip()
    except Exception as e:
        log.warning(f'Failed to generate month summary for {period_key}: {e}')
        summary_text = f'{len(entries)} записей, средний рейтинг {avg:.1f}/10.'

    summary_text = _strip_think(summary_text)
    if not summary_text:
        summary_text = f'{len(entries)} ???????, ??????? ??????? {avg:.1f}/10.'

    if existing:
        existing.summary = summary_text
        existing.avg_rating = round(avg, 1)
        existing.entry_count = len(entries)
        existing.created_at = datetime.utcnow()
    else:
        db.session.add(PeriodSummary(
            period_type='month',
            period_key=period_key,
            summary=summary_text,
            avg_rating=round(avg, 1),
            entry_count=len(entries),
            created_at=datetime.utcnow(),
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
            summaries_text = _truncate_to_tokens(llm, summaries_text, summary_cap)
        # Ensure we leave room for a minimum output + safety.
        available_for_prompt = max(0, int(n_ctx) - safety - min_output)
        available_for_summaries = max(0, available_for_prompt - base_tokens)
        if available_for_summaries > 0:
            summaries_text = _truncate_to_tokens(llm, summaries_text, available_for_summaries)
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
            summaries_text = _truncate_to_tokens(llm, summaries_text, new_limit)
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
        return profile

    if profile is None:
        profile = UserPsychProfile(
            profile_json=json.dumps(profile_data, ensure_ascii=False, indent=2),
            version=1,
            entries_analyzed=total_entries,
            updated_at=datetime.utcnow(),
        )
        db.session.add(profile)
    else:
        profile.profile_json = json.dumps(profile_data, ensure_ascii=False, indent=2)
        profile.version += 1
        profile.entries_analyzed = total_entries
        profile.updated_at = datetime.utcnow()

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
        found = MoodEntry.query.filter_by(date=d).all()
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
                found = MoodEntry.query.filter_by(date=d).all()
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

    # Layer 1: Recent raw entries (1 for greetings, 3 normally)
    recent_limit = 1 if light else 3
    recent = MoodEntry.query.order_by(MoodEntry.date.desc()).limit(recent_limit).all()
    if recent:
        rec_lines = []
        for e in recent:
            note = (e.note or '').strip()
            rec_lines.append(f'[{e.date.isoformat()}] {e.rating}/10. {note}')
        recent_section = RECENT_SECTION.format(entries_text='\n'.join(rec_lines))
    else:
        recent_section = ''

    full_text = SYSTEM_PROMPT.format(
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
                    profile_section=profile_section,
                    timeline_section=timeline_section,
                    relevant_section=relevant_section,
                    recent_section=recent_section,
                )

    return full_text
