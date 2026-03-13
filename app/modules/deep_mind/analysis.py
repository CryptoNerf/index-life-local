"""LLM-based topic naming for clustered diary entries.

Calls Qwen3 (borrowed from assistant module) to name each cluster
and assess its emotional weight.
"""
import logging
import os
import re

import numpy as np

from app import db
from app.models import MoodEntry, MindCluster, MindClusterEntry

log = logging.getLogger(__name__)

MIN_TOPIC_ENTRIES = max(2, int(os.getenv('DEEP_MIND_MIN_TOPIC_ENTRIES', '2')))
MAX_TOPIC_ENTRIES = max(
    MIN_TOPIC_ENTRIES,
    int(os.getenv('DEEP_MIND_MAX_TOPIC_ENTRIES', '15')),
)
MAX_NOTE_CHARS = int(os.getenv('DEEP_MIND_TOPIC_NOTE_CHARS', '500'))

FALLBACK_LABEL = 'Не удалось сформулировать тему'
FALLBACK_DESCRIPTION = (
    'Ответ модели не соответствовал формату. '
    'Попробуйте повторить анализ.'
)


def _get_llm():
    """Borrow the already-loaded LLM from the assistant module."""
    from app.modules.assistant.routes import _get_llm as assistant_get_llm
    return assistant_get_llm()


def _strip_think(text):
    """Strip ``<think>…</think>`` blocks from LLM output."""
    if not text:
        return ''
    cleaned = re.sub(r'(?is)<think>.*?</think>', '', text)
    cleaned = re.sub(r'(?is)<think>.*$', '', cleaned)
    cleaned = re.sub(r'(?is)</think>', '', cleaned)
    return cleaned.strip()


def _parse_fields(text):
    """Extract THEME/DESCRIPTION/WEIGHT (and Russian equivalents) from text."""
    label = ''
    description = ''
    weight = 0.5

    theme_re = re.compile(r'^(?:THEME|TOPIC|ТЕМА)\s*[:\-–—]\s*(.+)$', re.I)
    desc_re = re.compile(r'^(?:DESCRIPTION|DESC|ОПИСАНИЕ)\s*[:\-–—]\s*(.+)$', re.I)
    weight_re = re.compile(r'^(?:WEIGHT|ВЕС)\s*[:\-–—]\s*(.+)$', re.I)

    for raw in text.split('\n'):
        line = raw.strip()
        if not line:
            continue
        # Allow bullet prefixes
        line = line.lstrip('-•* ').strip()
        m = theme_re.match(line)
        if m:
            label = m.group(1).strip()
            continue
        m = desc_re.match(line)
        if m:
            description = m.group(1).strip()
            continue
        m = weight_re.match(line)
        if m:
            try:
                weight = float(m.group(1).strip())
                weight = max(0.0, min(1.0, weight))
            except ValueError:
                pass
    return label, description, weight


def _parse_topic_response(text):
    """Parse structured LLM response into ``(label, description, weight)``.

    Tries the full text first (in case fields are inside <think>),
    then falls back to think-stripped text.
    """
    # Try full text (fields may be inside <think>)
    label, description, weight = _parse_fields(text)
    if not label:
        # Try after stripping <think> blocks
        stripped = _strip_think(text)
        label, description, weight = _parse_fields(stripped)
    return label, description, weight


def _is_insufficient_label(label):
    if not label:
        return False
    lower = label.strip().lower()
    if 'not enough data' in lower or 'insufficient data' in lower:
        return True
    if 'недостаточно' in lower or 'не хватает' in lower:
        return True
    return False


def _looks_like_template(label):
    if not label:
        return False
    lower = label.strip().lower()
    suspects = [
        'template',
        'filled template',
        'example',
        'sample',
        'шаблон',
        'пример',
        'заполненн',
    ]
    return any(s in lower for s in suspects)


def _select_representative_entries(entries, max_entries):
    """Select entries that are both emotionally charged and textually rich."""
    # Sort by emotional extremity
    by_emotion = sorted(entries, key=lambda e: abs((e.rating or 5) - 5), reverse=True)
    # Sort by note length (longer notes = more context)
    by_length = sorted(entries, key=lambda e: len((e.note or '').strip()), reverse=True)

    half = max(max_entries // 2, 1)
    selected_ids = set()
    selected = []

    for e in by_emotion[:half]:
        if e.id not in selected_ids:
            selected_ids.add(e.id)
            selected.append(e)

    for e in by_length[:half]:
        if e.id not in selected_ids:
            selected_ids.add(e.id)
            selected.append(e)

    # Fill remaining slots from emotion-sorted
    for e in by_emotion:
        if len(selected) >= max_entries:
            break
        if e.id not in selected_ids:
            selected_ids.add(e.id)
            selected.append(e)

    # Sort chronologically for coherent reading
    selected.sort(key=lambda e: e.date)
    return selected[:max_entries]


def name_cluster(cluster_entry_ids, llm, max_entries=MAX_TOPIC_ENTRIES):
    """Call LLM to name a single cluster.

    Selects representative entries by emotional charge and text richness.
    Returns ``(label, description, emotional_weight)``.
    """
    from .prompts import TOPIC_NAMING_PROMPT, TOPIC_NAMING_FORCED_PROMPT

    entries = MoodEntry.query.filter(MoodEntry.id.in_(cluster_entry_ids)).all()
    if not entries:
        return 'Неизвестная тема', '', 0.5

    entry_count = len(entries)
    selected = _select_representative_entries(entries, max_entries)

    # Build context line with date range and average mood
    dates = [e.date for e in entries]
    avg_rating = sum(e.rating or 5 for e in entries) / len(entries)
    context_line = (
        f"Период: {min(dates).isoformat()} — {max(dates).isoformat()}. "
        f"Всего записей: {entry_count}. "
        f"Средняя оценка настроения: {avg_rating:.1f}/10."
    )

    lines = []
    for e in selected:
        note = (e.note or '').strip()[:MAX_NOTE_CHARS]
        lines.append(f'[{e.date.isoformat()}] Настроение: {e.rating}/10. {note}')
    entries_text = context_line + '\n\n' + '\n'.join(lines)

    def _call_prompt(prompt):
        result = llm.create_chat_completion(
            messages=[{
                'role': 'user',
                'content': prompt.format(
                    entries_text=entries_text,
                    entry_count=entry_count,
                ),
            }],
            max_tokens=512,
            temperature=0.4,
        )
        raw = result['choices'][0]['message']['content'].strip()
        return _parse_topic_response(raw)

    try:
        label, description, weight = _call_prompt(TOPIC_NAMING_PROMPT)
        label = (label or '').strip()

        # If LLM still says "insufficient" despite our prompt, force it
        if _is_insufficient_label(label):
            label, description, weight = _call_prompt(TOPIC_NAMING_FORCED_PROMPT)
            label = (label or '').strip()

        # Final fallback filters
        if _is_insufficient_label(label):
            # Still insufficient — use a generic but non-garbage label
            return 'Формирующийся паттерн', 'Тема требует больше данных для точной формулировки.', 0.3
        if _looks_like_template(label):
            return FALLBACK_LABEL, FALLBACK_DESCRIPTION, min(weight, 0.4)
        if not label:
            return FALLBACK_LABEL, FALLBACK_DESCRIPTION, min(weight, 0.4)
        if not description:
            description = 'Тема сформулирована на основе заметок.'

        return label, description, weight
    except Exception as e:
        log.warning('Topic naming failed for cluster (%d entries): %s',
                    len(cluster_entry_ids), e)
        return 'Тема', '', 0.5


def save_clusters_to_db(pipeline_result, llm, progress_cb=None):
    """Persist clustering result to DB.

    Clears old data, names each cluster via LLM, writes rows.
    *progress_cb(i, total)* is called after each cluster is named.
    """
    MindClusterEntry.query.delete()
    MindCluster.query.delete()
    db.session.commit()

    saved = []
    clusters = pipeline_result['clusters']
    total = len(clusters)

    for i, c in enumerate(clusters):
        label, description, weight = name_cluster(c['entry_ids'], llm)
        log.info('Cluster %d/%d: "%s" (%d entries, weight=%.2f)',
                 i + 1, total, label, c['size'], weight)

        cluster_obj = MindCluster(
            label=label,
            description=description,
            emotional_weight=weight,
            centroid=c['centroid'].astype(np.float32).tobytes(),
            entry_count=c['size'],
        )
        db.session.add(cluster_obj)
        db.session.flush()

        for entry_id in c['entry_ids']:
            db.session.add(MindClusterEntry(
                cluster_id=cluster_obj.id,
                entry_id=entry_id,
            ))

        saved.append(cluster_obj)
        if progress_cb:
            progress_cb(i + 1, total)

    db.session.commit()
    log.info('Saved %d clusters to DB', len(saved))
    return saved
