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


def cluster_embeddings(matrix, min_cluster_size=2, min_samples=1):
    """Cluster ``(N, dim)`` embedding matrix and return label array.

    * N < 6  → single cluster (label 0)
    * N >= 6 → HDBSCAN (falls back to AgglomerativeClustering)

    Label ``-1`` means noise (HDBSCAN only).
    """
    n = len(matrix)
    if n < 6:
        return np.zeros(n, dtype=int)

    try:
        import hdbscan
        clusterer = hdbscan.HDBSCAN(
            min_cluster_size=min_cluster_size,
            min_samples=min_samples,
            metric='euclidean',
            cluster_selection_epsilon=0.3,
        )
        return clusterer.fit_predict(matrix)
    except ImportError:
        log.info('hdbscan not installed, using AgglomerativeClustering')
        from sklearn.cluster import AgglomerativeClustering
        n_clusters = max(2, min(n // 5, 20))
        model = AgglomerativeClustering(
            n_clusters=n_clusters, metric='cosine', linkage='average',
        )
        return model.fit_predict(matrix)


def _reassign_noise(labels, matrix, min_similarity=0.35):
    """Assign noise points to the nearest cluster if close enough."""
    unique_labels = set(labels)
    unique_labels.discard(-1)
    if not unique_labels:
        return labels

    labels = labels.copy()

    # Compute L2-normalised centroids for existing clusters
    centroids = {}
    for lbl in unique_labels:
        mask = labels == lbl
        cent = matrix[mask].mean(axis=0)
        norm = np.linalg.norm(cent)
        if norm > 0:
            cent = cent / norm
        centroids[lbl] = cent

    noise_indices = np.where(labels == -1)[0]
    for idx in noise_indices:
        vec = matrix[idx].copy()
        norm = np.linalg.norm(vec)
        if norm > 0:
            vec = vec / norm
        best_sim = -1.0
        best_label = -1
        for lbl, cent in centroids.items():
            sim = float(np.dot(vec, cent))
            if sim > best_sim:
                best_sim = sim
                best_label = lbl
        if best_sim >= min_similarity:
            labels[idx] = best_label

    return labels


def _micro_cluster_noise(labels, matrix, similarity_threshold=0.45):
    """Create small clusters from remaining noise entries."""
    noise_indices = np.where(labels == -1)[0]
    if len(noise_indices) < 2:
        return labels

    labels = labels.copy()
    next_label = int(labels.max()) + 1

    # Normalise noise vectors
    noise_vecs = matrix[noise_indices].copy()
    norms = np.linalg.norm(noise_vecs, axis=1, keepdims=True)
    norms[norms == 0] = 1
    noise_vecs = noise_vecs / norms

    # Pairwise cosine similarity
    sim_matrix = noise_vecs @ noise_vecs.T

    # Greedy grouping
    assigned = set()
    for i in range(len(noise_indices)):
        if i in assigned:
            continue
        group = [i]
        for j in range(i + 1, len(noise_indices)):
            if j in assigned:
                continue
            if sim_matrix[i, j] >= similarity_threshold:
                group.append(j)
        if len(group) >= 2:
            for g in group:
                labels[noise_indices[g]] = next_label
                assigned.add(g)
            next_label += 1

    return labels


def compute_centroid(vecs):
    """L2-normalised mean of embedding vectors."""
    centroid = vecs.mean(axis=0)
    norm = np.linalg.norm(centroid)
    if norm > 0:
        centroid = centroid / norm
    return centroid.astype(np.float32)


def run_clustering_pipeline():
    """Full pipeline: load embeddings → cluster → reassign noise → return result.

    Does **not** touch the DB — the caller handles persistence.

    Returns dict with keys:
    * ``clusters`` – list of ``{label_index, entry_ids, centroid, size}``
    * ``noise_entry_ids`` – entries that couldn't be assigned
    * ``total_entries``
    * ``edges`` – ``[(i, j, similarity), ...]`` for pairs with sim > 0.3
    """
    entry_ids, matrix = load_embeddings()
    if len(entry_ids) == 0:
        return {'clusters': [], 'noise_entry_ids': [], 'total_entries': 0, 'edges': []}

    labels = cluster_embeddings(matrix)
    labels = _reassign_noise(labels, matrix)
    labels = _micro_cluster_noise(labels, matrix)

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
