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
    EntryEmbedding, UserPsychProfile,
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


def search_relevant_entries(query: str, top_k: int = 5) -> list[MoodEntry]:
    """Find most semantically relevant entries for a query."""
    query_vec = embed_query(query)

    all_embs = EntryEmbedding.query.all()
    if not all_embs:
        return []

    entry_ids = []
    scores = []
    for emb in all_embs:
        vec = np.frombuffer(emb.embedding, dtype=np.float32)
        score = np.dot(query_vec, vec)  # cosine sim (vectors are normalized)
        entry_ids.append(emb.entry_id)
        scores.append(score)

    scores = np.array(scores)
    top_indices = np.argsort(scores)[::-1][:top_k]

    result_ids = [entry_ids[i] for i in top_indices]
    entries = MoodEntry.query.filter(MoodEntry.id.in_(result_ids)).all()
    # Sort by relevance score
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
        summary_text = note[:200] + ('...' if len(note) > 200 else '')

    summary_text = _strip_think(summary_text)
    if not summary_text:
        summary_text = f'{len(entries)} entries, avg rating {avg:.1f}/10.'

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

    # Truncate if too long (keep ~8000 tokens worth ≈ 16000 chars for Russian)
    if len(summaries_text) > 16000:
        summaries_text = summaries_text[-16000:]

    try:
        prompt = PROFILE_PROMPT.format(summaries_text=summaries_text)
        result = llm.create_chat_completion(
            messages=[{'role': 'user', 'content': prompt}],
            max_tokens=2048,
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
    """Extract JSON object from LLM response text."""
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
    return {}


# ── Context assembly ────────────────────────────────────────────

def assemble_context(user_message: str) -> str:
    """Build the full system prompt from all 4 memory layers."""

    # Layer 4: Profile
    profile = UserPsychProfile.query.first()
    if profile and profile.profile_json and profile.profile_json != '{}':
        profile_section = PROFILE_SECTION.format(profile_text=profile.profile_json)
    else:
        profile_section = ''

    # Layer 3: Monthly timeline
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

    # Layer 2: Relevant entries via semantic search
    try:
        relevant_entries = search_relevant_entries(user_message, top_k=5)
        if relevant_entries:
            rel_lines = []
            for e in relevant_entries:
                note = (e.note or '').strip()
                rel_lines.append(f'[{e.date.isoformat()}] {e.rating}/10. {note}')
            relevant_section = RELEVANT_SECTION.format(
                entries_text='\n'.join(rel_lines)
            )
        else:
            relevant_section = ''
    except Exception as e:
        log.warning(f'Vector search failed: {e}')
        relevant_section = ''

    # Layer 1: Recent raw entries (last 3)
    recent = MoodEntry.query.order_by(MoodEntry.date.desc()).limit(3).all()
    if recent:
        rec_lines = []
        for e in recent:
            note = (e.note or '').strip()
            rec_lines.append(f'[{e.date.isoformat()}] {e.rating}/10. {note}')
        recent_section = RECENT_SECTION.format(entries_text='\n'.join(rec_lines))
    else:
        recent_section = ''

    return SYSTEM_PROMPT.format(
        profile_section=profile_section,
        timeline_section=timeline_section,
        relevant_section=relevant_section,
        recent_section=recent_section,
    )
