#!/usr/bin/env python3
"""Visualize diary entry embeddings as a 2D scatter — a "constellation of thoughts".

Reads `entry_embeddings`, `mood_entries`, `mind_clusters` and
`mind_cluster_entries` from a diary.db, projects the high-dimensional
e5 vectors down to 2D, and writes a self-contained SVG where every
entry is a coloured point.

By default it colours by topic cluster (the same clusters the in-app
neural map uses); pass `--color mood` for a red→green mood gradient.
The output SVG has no external CSS — open it in any browser, Figma,
Illustrator, Inkscape. Perfect for a promo asset.

Usage:
    python tools/visualize_embeddings.py
    python tools/visualize_embeddings.py --db /path/to/diary.db --out promo.svg
    python tools/visualize_embeddings.py --method umap --labels --bg dark
    python tools/visualize_embeddings.py --color mood --width 2400 --height 1200

Privacy note: only embedding coordinates, mood ratings, and LLM-generated
topic labels are read — never the actual note text. The labels (e.g.
"работа", "тревога") are the same ones the neural-map UI already shows.
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from pathlib import Path

import numpy as np


# ── data loading ────────────────────────────────────────────────────────────

def load(db_path: str):
    """Return (X, moods, dates, cluster_ids, cluster_labels) from the DB.

    Excludes soft-deleted entries and rows without an embedding.
    """
    con = sqlite3.connect(db_path)
    rows = con.execute(
        """
        SELECT e.entry_id, e.embedding, m.rating, m.date,
               mce.cluster_id, mc.label
        FROM   entry_embeddings e
        JOIN   mood_entries m  ON m.id = e.entry_id
        LEFT JOIN mind_cluster_entries mce ON mce.entry_id = e.entry_id
        LEFT JOIN mind_clusters mc         ON mc.id = mce.cluster_id
        WHERE  COALESCE(m.deleted, 0) = 0
          AND  e.embedding IS NOT NULL
        """
    ).fetchall()
    con.close()

    if not rows:
        sys.exit(
            "No embeddings found. Open the app once with the AI psychologist "
            "module installed so it can backfill embeddings, then re-run."
        )

    vecs, moods, dates, cids, clabels = [], [], [], [], []
    for _eid, blob, rating, date, cid, label in rows:
        vecs.append(np.frombuffer(blob, dtype=np.float32))
        moods.append(rating)
        dates.append(date)
        cids.append(cid)
        clabels.append(label)
    X = np.vstack(vecs).astype(np.float64)
    return X, moods, dates, cids, clabels


# ── projection ──────────────────────────────────────────────────────────────

def project(X: np.ndarray, method: str) -> np.ndarray:
    """Project (N, D) → (N, 2). Falls back gracefully if a library is missing."""
    n = len(X)
    if n < 5:
        method = 'pca'  # tsne/umap need more points to make sense

    if method == 'umap':
        try:
            import umap  # type: ignore
            return umap.UMAP(
                n_components=2, random_state=42,
                n_neighbors=min(15, max(2, n - 1)), min_dist=0.12,
            ).fit_transform(X)
        except ImportError:
            print('umap-learn not installed — falling back to t-SNE',
                  file=sys.stderr)
            method = 'tsne'

    if method == 'tsne':
        try:
            from sklearn.manifold import TSNE
            perp = max(5, min(30, n // 4))
            return TSNE(
                n_components=2, random_state=42, perplexity=perp,
                init='pca', learning_rate='auto',
            ).fit_transform(X)
        except ImportError:
            print('scikit-learn not installed — falling back to PCA',
                  file=sys.stderr)

    # PCA via SVD — pure numpy, always available.
    Xc = X - X.mean(axis=0)
    _, _, Vt = np.linalg.svd(Xc, full_matrices=False)
    return Xc @ Vt[:2].T


# ── colour helpers ──────────────────────────────────────────────────────────

def hsl_to_hex(h: float, s: float, l: float) -> str:
    """h, s, l ∈ [0, 1] → "#rrggbb"."""
    c = (1 - abs(2 * l - 1)) * s
    x = c * (1 - abs((h * 6) % 2 - 1))
    sector = min(int(h * 6), 5)
    rgb = [
        (c, x, 0), (x, c, 0), (0, c, x),
        (0, x, c), (x, 0, c), (c, 0, x),
    ][sector]
    m = l - c / 2
    return '#' + ''.join(f'{int(round((v + m) * 255)):02x}' for v in rgb)


def cluster_palette(n: int, theme: str) -> list[str]:
    sat, light = (0.65, 0.62) if theme == 'dark' else (0.55, 0.45)
    # Golden-ratio hop around the hue wheel for maximally-distinct neighbours.
    out, h = [], 0.0
    for _ in range(n):
        out.append(hsl_to_hex(h, sat, light))
        h = (h + 0.61803398875) % 1.0
    return out


def mood_color(rating, theme: str) -> str:
    """1 → muted red, 10 → muted green; None → neutral grey."""
    if rating is None:
        return '#888' if theme == 'light' else '#555'
    t = max(0.0, min(1.0, (rating - 1) / 9))
    r0, g0, b0 = 0xc8, 0x4c, 0x4c
    r1, g1, b1 = 0x4c, 0xb0, 0x50
    rr = int(r0 + (r1 - r0) * t)
    gg = int(g0 + (g1 - g0) * t)
    bb = int(b0 + (b1 - b0) * t)
    return f'#{rr:02x}{gg:02x}{bb:02x}'


# ── SVG writer ──────────────────────────────────────────────────────────────

def _xml_escape(s: str) -> str:
    return (s.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
             .replace('"', '&quot;'))


def write_svg(out_path: str, X2: np.ndarray, colors: list[str], theme: str,
              width: int, height: int,
              labels: list[tuple[str, np.ndarray]] | None = None) -> None:
    """Render the 2D points as a self-contained SVG."""
    margin = 60
    x0, y0 = X2[:, 0].min(), X2[:, 1].min()
    x1, y1 = X2[:, 0].max(), X2[:, 1].max()
    rngx, rngy = max(x1 - x0, 1e-9), max(y1 - y0, 1e-9)

    def to_canvas(p):
        return (
            margin + (p[0] - x0) / rngx * (width - 2 * margin),
            margin + (p[1] - y0) / rngy * (height - 2 * margin),
        )

    bg = '#0a0a0a' if theme == 'dark' else '#ffffff'
    label_fg = '#eee' if theme == 'dark' else '#222'
    radius = 4.5
    opacity = 0.78

    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'viewBox="0 0 {width} {height}" width="{width}" height="{height}">',
        f'  <rect width="100%" height="100%" fill="{bg}"/>',
    ]
    for i, p in enumerate(X2):
        cx, cy = to_canvas(p)
        lines.append(
            f'  <circle cx="{cx:.1f}" cy="{cy:.1f}" r="{radius}" '
            f'fill="{colors[i]}" fill-opacity="{opacity}"/>'
        )
    if labels:
        for label, pos in labels:
            cx, cy = to_canvas(pos)
            lines.append(
                f'  <text x="{cx:.1f}" y="{cy:.1f}" fill="{label_fg}" '
                f'font-family="Times New Roman, serif" font-size="14" '
                f'text-anchor="middle" font-style="italic" '
                f'paint-order="stroke" stroke="{bg}" stroke-width="3" '
                f'stroke-linejoin="round">{_xml_escape(label)}</text>'
            )
    lines.append('</svg>')
    Path(out_path).write_text('\n'.join(lines) + '\n', encoding='utf-8')


# ── main ────────────────────────────────────────────────────────────────────

def main() -> None:
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument('--db', default='diary.db',
                   help='Path to diary.db (default: ./diary.db). '
                        'macOS user data: ~/Library/Application Support/index.life/diary.db')
    p.add_argument('--out', default='embeddings.svg', help='Output SVG path')
    p.add_argument('--method', default='tsne', choices=['umap', 'tsne', 'pca'])
    p.add_argument('--color', default='cluster', choices=['cluster', 'mood'])
    p.add_argument('--bg', default='light', choices=['light', 'dark'])
    p.add_argument('--width', type=int, default=1600)
    p.add_argument('--height', type=int, default=900)
    p.add_argument('--labels', action='store_true',
                   help='Draw cluster names at each cluster centroid')
    args = p.parse_args()

    if not os.path.exists(args.db):
        sys.exit(
            f'DB not found: {args.db}\n'
            'On macOS try: ~/Library/Application Support/index.life/diary.db'
        )

    X, moods, _dates, cids, clabels = load(args.db)
    print(f'Loaded {len(X)} embeddings (dim={X.shape[1]}); '
          f'projecting with {args.method}…')
    X2 = project(X, args.method)

    if args.color == 'cluster' and any(c is not None for c in cids):
        uniq = sorted({c for c in cids if c is not None})
        pal = cluster_palette(len(uniq), args.bg)
        cmap = {cid: pal[i] for i, cid in enumerate(uniq)}
        unclassified = '#888' if args.bg == 'light' else '#555'
        colors = [cmap[c] if c is not None else unclassified for c in cids]
        labels = None
        if args.labels:
            labels = []
            for cid in uniq:
                idxs = [i for i, c in enumerate(cids) if c == cid]
                name = next((clabels[i] for i in idxs if clabels[i]), f'#{cid}')
                pos = X2[idxs].mean(axis=0)
                labels.append((name, pos))
    else:
        if args.color == 'cluster':
            print('No clusters in DB yet — colouring by mood instead.',
                  file=sys.stderr)
        colors = [mood_color(m, args.bg) for m in moods]
        labels = None

    write_svg(args.out, X2, colors, args.bg, args.width, args.height,
              labels=labels)
    print(f'Wrote {args.out} ({args.width}×{args.height})')


if __name__ == '__main__':
    main()
