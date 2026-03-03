"""LLM-based topic naming for clustered diary entries.

Calls Qwen3 (borrowed from assistant module) to name each cluster
and assess its emotional weight.
"""
import logging
import re

import numpy as np

from app import db
from app.models import MoodEntry, MindCluster, MindClusterEntry

log = logging.getLogger(__name__)


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
    """Extract ТЕМА/ОПИСАНИЕ/ВЕС fields from text."""
    label = ''
    description = ''
    weight = 0.5
    for line in text.split('\n'):
        line = line.strip()
        up = line.upper()
        if up.startswith('ТЕМА:') or up.startswith('ТЕМА :'):
            label = line.split(':', 1)[1].strip()
        elif up.startswith('ОПИСАНИЕ:') or up.startswith('ОПИСАНИЕ :'):
            description = line.split(':', 1)[1].strip()
        elif up.startswith('ВЕС:') or up.startswith('ВЕС :'):
            try:
                weight = float(line.split(':', 1)[1].strip())
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
    if not label:
        # Last resort: first non-empty line as label
        for line in _strip_think(text).split('\n'):
            line = line.strip()
            if line:
                label = line[:60]
                break
        if not label:
            label = 'Тема'
    return label, description, weight


def name_cluster(cluster_entry_ids, llm, max_entries=8):
    """Call LLM to name a single cluster.

    Selects the most emotionally charged entries (rating furthest from 5).
    Returns ``(label, description, emotional_weight)``.
    """
    from .prompts import TOPIC_NAMING_PROMPT

    entries = MoodEntry.query.filter(MoodEntry.id.in_(cluster_entry_ids)).all()
    if not entries:
        return 'Неизвестная тема', '', 0.5

    entries_sorted = sorted(entries, key=lambda e: abs((e.rating or 5) - 5), reverse=True)
    selected = entries_sorted[:max_entries]

    lines = []
    for e in selected:
        note = (e.note or '').strip()[:300]
        lines.append(f'[{e.date.isoformat()}] Настроение: {e.rating}/10. {note}')
    entries_text = '\n'.join(lines)

    try:
        result = llm.create_chat_completion(
            messages=[{
                'role': 'user',
                'content': TOPIC_NAMING_PROMPT.format(entries_text=entries_text),
            }],
            max_tokens=512,
            temperature=0.4,
        )
        raw = result['choices'][0]['message']['content'].strip()
        return _parse_topic_response(raw)
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
