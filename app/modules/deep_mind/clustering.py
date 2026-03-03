"""Embedding-based topic clustering for the deep-mind module.

Reuses EntryEmbedding rows already computed by the assistant module.
"""
import logging

import numpy as np

from app.models import EntryEmbedding, MoodEntry

log = logging.getLogger(__name__)


def load_embeddings():
    """Load all entry embeddings from DB.

    Returns ``(entry_ids, matrix)`` where *matrix* is ``(N, 384)`` float32.
    Entries without a note are skipped.
    """
    rows = EntryEmbedding.query.all()
    entry_ids = []
    vecs = []
    for row in rows:
        entry = MoodEntry.query.get(row.entry_id)
        if entry and entry.note and entry.note.strip():
            vec = np.frombuffer(row.embedding, dtype=np.float32).copy()
            entry_ids.append(row.entry_id)
            vecs.append(vec)
    if not vecs:
        return [], np.empty((0, 384), dtype=np.float32)
    return entry_ids, np.stack(vecs)


def cluster_embeddings(matrix, min_cluster_size=3, min_samples=2):
    """Cluster ``(N, dim)`` embedding matrix and return label array.

    * N < 10  → single cluster (label 0)
    * N >= 10 → HDBSCAN (falls back to AgglomerativeClustering)

    Label ``-1`` means noise (HDBSCAN only).
    """
    n = len(matrix)
    if n < 10:
        return np.zeros(n, dtype=int)

    try:
        import hdbscan
        clusterer = hdbscan.HDBSCAN(
            min_cluster_size=min_cluster_size,
            min_samples=min_samples,
            metric='euclidean',
        )
        return clusterer.fit_predict(matrix)
    except ImportError:
        log.info('hdbscan not installed, using AgglomerativeClustering')
        from sklearn.cluster import AgglomerativeClustering
        n_clusters = max(2, min(n // 5, 15))
        model = AgglomerativeClustering(
            n_clusters=n_clusters, metric='cosine', linkage='average',
        )
        return model.fit_predict(matrix)


def compute_centroid(vecs):
    """L2-normalised mean of embedding vectors."""
    centroid = vecs.mean(axis=0)
    norm = np.linalg.norm(centroid)
    if norm > 0:
        centroid = centroid / norm
    return centroid.astype(np.float32)


def run_clustering_pipeline():
    """Full pipeline: load embeddings → cluster → return structured result.

    Does **not** touch the DB — the caller handles persistence.

    Returns dict with keys:
    * ``clusters`` – list of ``{label_index, entry_ids, centroid, size}``
    * ``noise_entry_ids`` – entries labelled ``-1``
    * ``total_entries``
    * ``edges`` – ``[(i, j, similarity), ...]`` for pairs with sim > 0.3
    """
    entry_ids, matrix = load_embeddings()
    if len(entry_ids) == 0:
        return {'clusters': [], 'noise_entry_ids': [], 'total_entries': 0, 'edges': []}

    labels = cluster_embeddings(matrix)

    label_to_indices = {}
    for idx, label in enumerate(labels):
        label_to_indices.setdefault(int(label), []).append(idx)

    noise_entry_ids = [entry_ids[i] for i in label_to_indices.pop(-1, [])]

    clusters = []
    centroids = []
    for label, indices in sorted(label_to_indices.items()):
        cluster_vecs = matrix[indices]
        centroid = compute_centroid(cluster_vecs)
        centroids.append(centroid)
        clusters.append({
            'label_index': label,
            'entry_ids': [entry_ids[i] for i in indices],
            'centroid': centroid,
            'size': len(indices),
        })

    # Edges: cosine similarity between cluster centroids
    edge_threshold = 0.3
    edges = []
    for i in range(len(centroids)):
        for j in range(i + 1, len(centroids)):
            sim = float(np.dot(centroids[i], centroids[j]))
            if sim > edge_threshold:
                edges.append((i, j, round(sim, 3)))

    return {
        'clusters': clusters,
        'noise_entry_ids': noise_entry_ids,
        'total_entries': len(entry_ids),
        'edges': edges,
    }
