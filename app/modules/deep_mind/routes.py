# index.life — Local mood diary
# https://github.com/CryptoNerf/index-life-local
# Copyright (C) 2026 Émile Alexanyan
#
# Licensed under AGPL-3.0 with additional terms per Section 7
# (preservation of author attribution, no misrepresentation of
# origin). See LICENSE and COPYRIGHT at the root of this project.
"""Routes for the deep-mind neural map module."""
import logging
import os

import numpy as np
from flask import render_template, jsonify, current_app

from app import db
from app.models import MindCluster, MindClusterEntry, MoodEntry
from . import bp
from .analysis import MIN_TOPIC_ENTRIES, _is_insufficient_label

log = logging.getLogger(__name__)

# How many nearest topics each neuron links to. A flat similarity cutoff
# can't work here: multilingual-e5 centroids of *any* two diary topics sit
# in a narrow high band (~0.85–0.99), so any fixed threshold keeps either
# every pair or none. Instead we keep each neuron's top-K most-similar
# neighbours, so the map links genuinely-closer topics rather than wiring
# everything to everything. Override with NEURAL_EDGE_TOP_K.
try:
    _EDGE_TOP_K = max(1, int(os.environ.get('NEURAL_EDGE_TOP_K', '3')))
except ValueError:
    _EDGE_TOP_K = 3
_EDGE_MIN_SIM = 0.3  # absolute floor; rarely binds with these embeddings


def _confidence_for_size(size):
    if size <= 1:
        return 0.15
    if size == 2:
        return 0.25
    if size <= 3:
        return 0.4
    if size <= 5:
        return 0.55
    if size <= 8:
        return 0.7
    if size <= 12:
        return 0.82
    return 0.9


def _confidence_label(conf):
    if conf < 0.35:
        return 'низкая'
    if conf < 0.65:
        return 'средняя'
    return 'высокая'


def _data_note(size):
    if size < MIN_TOPIC_ENTRIES:
        return (
            f'Слишком мало данных: {size} записей. '
            f'Для устойчивой темы нужно минимум {MIN_TOPIC_ENTRIES}.'
        )
    if size < MIN_TOPIC_ENTRIES + 2:
        return 'Осторожная гипотеза: данных пока немного.'
    return ''


def _snippet(note, limit=140):
    text = ' '.join((note or '').split())
    if len(text) > limit:
        return text[:limit].rstrip() + '…'
    return text


def _build_evidence(entries, limit=3):
    candidates = [e for e in entries if (e.note or '').strip()]
    candidates.sort(
        key=lambda e: (abs((e.rating or 5) - 5), len((e.note or '').strip())),
        reverse=True,
    )
    evidence = []
    for e in candidates[:limit]:
        snippet = _snippet(e.note)
        if not snippet:
            continue
        evidence.append({
            'date': e.date.isoformat(),
            'rating': e.rating,
            'snippet': snippet,
        })
    return evidence


@bp.route('/')
def neural_map():
    """Main neural map visualisation page."""
    return render_template('deep_mind/neural_map.html')


@bp.route('/api/graph')
def api_graph():
    """Return graph data as JSON for d3-force."""
    clusters = MindCluster.query.all()
    clusters = [
        c for c in clusters
        if (c.entry_count or 0) >= MIN_TOPIC_ENTRIES
        and not _is_insufficient_label(c.label)
    ]
    if not clusters:
        return jsonify({'nodes': [], 'edges': [], 'status': 'empty'})

    nodes = []
    centroids = []
    for c in clusters:
        member_ids = [
            me.entry_id
            for me in MindClusterEntry.query.filter_by(cluster_id=c.id).all()
        ]
        entries = (MoodEntry.query
                   .filter(MoodEntry.id.in_(member_ids),
                           MoodEntry.deleted == False)  # noqa: E712
                   .order_by(MoodEntry.date.desc())
                   .all())
        entries_display = entries[:20]
        entries_data = []
        for entry in entries_display:
            entries_data.append({
                'date': entry.date.isoformat(),
                'rating': entry.rating,
                'note': entry.note or '',
            })

        entry_count = c.entry_count or len(member_ids)
        confidence = _confidence_for_size(entry_count)
        confidence_label = _confidence_label(confidence)
        data_note = _data_note(entry_count)
        low_data = entry_count < MIN_TOPIC_ENTRIES
        evidence = _build_evidence(entries, limit=3)

        if c.centroid:
            vec = np.frombuffer(c.centroid, dtype=np.float32).copy()
        else:
            vec = np.zeros(384, dtype=np.float32)
        centroids.append(vec)

        nodes.append({
            'id': c.id,
            'label': c.label,
            'description': c.description or '',
            'size': entry_count,
            'weight': round(c.emotional_weight, 3),
            'entries': entries_data,
            'confidence': round(confidence, 2),
            'confidence_label': confidence_label,
            'data_note': data_note,
            'low_data': low_data,
            'min_entries': MIN_TOPIC_ENTRIES,
            'evidence': evidence,
        })

    # Edges: connect each topic only to its K most-similar topics (union),
    # not every pair above a flat cutoff (which would link all-to-all — see
    # _EDGE_TOP_K note above).
    edges = []
    n = len(clusters)
    if n >= 2:
        sim = np.zeros((n, n), dtype=np.float64)
        for i in range(n):
            for j in range(i + 1, n):
                sim[i, j] = sim[j, i] = float(np.dot(centroids[i], centroids[j]))

        k = min(_EDGE_TOP_K, n - 1)
        kept = set()
        for i in range(n):
            # take this neuron's own K nearest neighbours (most similar first);
            # the set dedups, so a popular topic may end up with a few more.
            taken = 0
            for j in np.argsort(sim[i])[::-1]:
                if j == i or sim[i, j] < _EDGE_MIN_SIM:
                    continue
                a, b = (i, int(j)) if i < j else (int(j), i)
                kept.add((a, b))
                taken += 1
                if taken >= k:
                    break

        for a, b in sorted(kept):
            edges.append({
                'source': clusters[a].id,
                'target': clusters[b].id,
                'strength': round(float(sim[a, b]), 3),
            })

    return jsonify({'nodes': nodes, 'edges': edges, 'status': 'ready'})


@bp.route('/api/status')
def api_status():
    """Return background analysis status."""
    from .background import get_status
    return jsonify(get_status())


@bp.route('/api/analyze', methods=['POST'])
def api_analyze():
    """Trigger a new clustering + naming run in background.

    Manual (user pressed "Analyze") → force=True so it bypasses the
    debounce that throttles the automatic post-save runs.
    """
    from .background import analyze_async
    analyze_async(current_app._get_current_object(), force=True)
    return jsonify({'status': 'started'})
