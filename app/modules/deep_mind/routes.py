"""Routes for the deep-mind neural map module."""
import logging

import numpy as np
from flask import render_template, jsonify, current_app

from app import db
from app.models import MindCluster, MindClusterEntry, MoodEntry
from . import bp

log = logging.getLogger(__name__)


@bp.route('/')
def neural_map():
    """Main neural map visualisation page."""
    return render_template('deep_mind/neural_map.html')


@bp.route('/api/graph')
def api_graph():
    """Return graph data as JSON for d3-force."""
    clusters = MindCluster.query.all()
    if not clusters:
        return jsonify({'nodes': [], 'edges': [], 'status': 'empty'})

    nodes = []
    centroids = []
    for c in clusters:
        member_ids = [
            me.entry_id
            for me in MindClusterEntry.query.filter_by(cluster_id=c.id).limit(20).all()
        ]
        entries_data = []
        for entry in (MoodEntry.query
                      .filter(MoodEntry.id.in_(member_ids))
                      .order_by(MoodEntry.date.desc())
                      .all()):
            entries_data.append({
                'date': entry.date.isoformat(),
                'rating': entry.rating,
                'note': entry.note or '',
            })

        if c.centroid:
            vec = np.frombuffer(c.centroid, dtype=np.float32).copy()
        else:
            vec = np.zeros(384, dtype=np.float32)
        centroids.append(vec)

        nodes.append({
            'id': c.id,
            'label': c.label,
            'description': c.description or '',
            'size': c.entry_count,
            'weight': round(c.emotional_weight, 3),
            'entries': entries_data,
        })

    # Edges from centroid cosine similarity
    edges = []
    for i in range(len(clusters)):
        for j in range(i + 1, len(clusters)):
            sim = float(np.dot(centroids[i], centroids[j]))
            if sim > 0.3:
                edges.append({
                    'source': clusters[i].id,
                    'target': clusters[j].id,
                    'strength': round(sim, 3),
                })

    return jsonify({'nodes': nodes, 'edges': edges, 'status': 'ready'})


@bp.route('/api/status')
def api_status():
    """Return background analysis status."""
    from .background import get_status
    return jsonify(get_status())


@bp.route('/api/analyze', methods=['POST'])
def api_analyze():
    """Trigger a new clustering + naming run in background."""
    from .background import analyze_async
    analyze_async(current_app._get_current_object())
    return jsonify({'status': 'started'})
