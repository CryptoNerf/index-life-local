"""Promo motion graphics — Neural Map intro (~17 s, 1080p).

The visual story of how index.life's Neural Map gets built:

    entries scatter across the canvas
        → drift together by meaning
            → coalesce into neurons
                → each neuron labelled with a *hidden question*
                    → link to closest neighbours

Important: the labels here are NOT simple topic tags ("work", "family").
The actual feature uses a psychoanalytic prompt
(app/modules/deep_mind/prompts.py) and produces formulations like
"Страх потери контроля" — internal questions or problems the user may
not have consciously articulated. The labels below are sample
formulations of exactly that kind, so the promo doesn't misrepresent
what users will actually see.

Render:
    pip install manim                # plus brew install ffmpeg pango cairo on macOS
    manim -qh promo/neural_map_intro.py NeuralMapIntro
    # output → media/videos/neural_map_intro/1080p60/NeuralMapIntro.mp4

Useful quality flags:
    -ql   480p / fast iteration
    -qm   720p
    -qh   1080p60 (recommended for promo)
    -qk   4K
"""
from manim import *
import numpy as np


# index.life-friendly palette ─────────────────────────────────────
BG = "#0a0a0a"
PALETTE = [
    "#009AFA",   # brand cyan
    "#FFA340",   # warm amber
    "#E14F88",   # rose
    "#7DC36A",   # leaf green
    "#B780E8",   # lilac
    "#FFD24A",   # mustard
    "#5DD3D3",   # mint
]

# HIDDEN_QUESTIONS — each one is a sample of what the LLM actually
# produces for a cluster: a 3-6 word psychoanalytic hypothesis about an
# inner question or problem behind the entries (NOT a topic tag like
# "work" or "family"). Match the tone of the examples in
# app/modules/deep_mind/prompts.py.
#
# Position is the cluster centre on the manim canvas (~ -7..7 in x,
# -4..4 in y). Shorter labels go in tight spots; the longest one is
# parked on the right edge where it has nothing to bump into.
HIDDEN_QUESTIONS = [
    ("Поиск смысла в рутине",         np.array([-4.4,  1.7, 0])),
    ("Потребность в признании",       np.array([ 4.0,  1.4, 0])),
    ("Конфликт долга и желаний",      np.array([-3.6, -1.8, 0])),
    ("Страх потери контроля",         np.array([ 3.2, -2.0, 0])),
    ("Сопротивление переменам",       np.array([ 0.2,  2.3, 0])),
    ("Тоска по близости",             np.array([-0.6, -2.5, 0])),
    ("Усталость от ответственности",  np.array([ 5.4, -0.4, 0])),
]
ENTRIES_PER_TOPIC = [18, 15, 11, 14, 19, 9, 12]   # ~98 dots total


def _rand_in_ellipse(center, rx, ry, rng):
    """Uniform random point inside an ellipse around `center`."""
    r = np.sqrt(rng.random())
    theta = rng.uniform(0, 2 * np.pi)
    return center + np.array([rx * r * np.cos(theta),
                              ry * r * np.sin(theta), 0])


class NeuralMapIntro(Scene):
    def construct(self):
        self.camera.background_color = BG
        rng = np.random.default_rng(42)

        # ── ACT 1 ─ entries scattered across the canvas ──────────
        cluster_groups = []     # one VGroup per topic (used in ACT 3)
        all_dots = []           # flat list for the staggered fade-in
        dot_to_centre = []      # parallel: each dot's target cluster

        for (name, center), color, n in zip(HIDDEN_QUESTIONS, PALETTE, ENTRIES_PER_TOPIC):
            group = VGroup()
            for _ in range(n):
                start = np.array([
                    rng.uniform(-6.6, 6.6),
                    rng.uniform(-3.5, 3.5), 0,
                ])
                d = Dot(start, radius=0.04, color=color, fill_opacity=0.65)
                group.add(d)
                all_dots.append(d)
                dot_to_centre.append((d, center))
            cluster_groups.append(group)

        self.play(
            LaggedStart(
                *[FadeIn(d, scale=0.6) for d in all_dots],
                lag_ratio=0.02,
            ),
            run_time=2.2,
        )
        self.wait(0.4)

        # ── ACT 2 ─ dots drift toward their cluster centres ──────
        drift = []
        for d, center in dot_to_centre:
            target = _rand_in_ellipse(center, 0.7, 0.5, rng)
            drift.append(d.animate.move_to(target))
        self.play(*drift, run_time=2.4, rate_func=smooth)
        self.wait(0.3)

        # ── ACT 3 ─ each cloud materialises into a neuron ────────
        neurons = []
        for (name, center), color in zip(HIDDEN_QUESTIONS, PALETTE):
            halo = Circle(radius=0.55, color=color, fill_opacity=0.10,
                          stroke_width=0).move_to(center)
            body = Circle(radius=0.22, color=color, fill_opacity=0.95,
                          stroke_width=0).move_to(center)
            neurons.append({
                'name': name, 'center': center, 'color': color,
                'body': body, 'halo': halo,
            })

        materialise = [
            d.animate.move_to(center).set_opacity(0).scale(0.5)
            for d, center in dot_to_centre
        ]
        body_creates = [GrowFromCenter(n['body']) for n in neurons]
        halo_fades   = [FadeIn(n['halo'])         for n in neurons]
        self.play(*materialise, *body_creates, *halo_fades, run_time=1.4)
        self.wait(0.25)

        # ── ACT 4 ─ topic names appear next to neurons ───────────
        labels = []
        for n in neurons:
            # Smaller font than a typical topic-tag because the hypothesis
            # labels are 3-6 words, not one word.
            label = Text(n['name'], font="Times New Roman",
                         slant=ITALIC, color="#eeeeee", font_size=22)
            # Top-row neurons get labels BELOW; bottom-row ABOVE — so
            # nothing pokes off-frame and labels never collide with the
            # outro title later.
            offset = DOWN * 0.55 if n['center'][1] > 0.5 else UP * 0.55
            label.move_to(n['body'].get_center() + offset)
            labels.append(label)
        self.play(
            LaggedStart(
                *[FadeIn(l, shift=UP * 0.1) for l in labels],
                lag_ratio=0.08,
            ),
            run_time=1.4,
        )
        self.wait(0.3)

        # ── ACT 5 ─ each neuron links to its 3 closest neighbours ─
        # Same top-K rule the in-app code uses (see deep_mind/routes.py).
        positions = np.array([n['center'] for n in neurons])
        K = 3
        edges = set()
        for i in range(len(positions)):
            order = np.argsort(np.linalg.norm(positions - positions[i], axis=1))
            taken = 0
            for j in order:
                j = int(j)
                if j == i:
                    continue
                a, b = (i, j) if i < j else (j, i)
                edges.add((a, b))
                taken += 1
                if taken >= K:
                    break

        lines = [
            Line(positions[a], positions[b],
                 stroke_color="#ffffff",
                 stroke_opacity=0.0,       # animated up to 0.20 below
                 stroke_width=1.0)
            for (a, b) in sorted(edges)
        ]
        lines_group = VGroup(*lines)

        # Add lines first, then push neurons + labels to the front so
        # the connecting lines never cut over the neuron bodies.
        self.add(lines_group)
        for n in neurons:
            self.bring_to_front(n['halo'])
            self.bring_to_front(n['body'])
        for l in labels:
            self.bring_to_front(l)

        self.play(
            LaggedStart(
                *[l.animate.set_stroke(opacity=0.20) for l in lines],
                lag_ratio=0.05,
            ),
            run_time=1.4,
        )
        self.wait(0.5)

        # ── OUTRO ─ subtle compose-down + title ──────────────────
        graph = VGroup(
            *[n['halo'] for n in neurons],
            *[n['body'] for n in neurons],
            *labels,
            lines_group,
        )
        title = Text("Нейронная карта", font="Times New Roman",
                     color="#ffffff", font_size=44)
        subtitle = Text("скрытые вопросы из твоих записей",
                        font="Times New Roman", slant=ITALIC,
                        color="#a0a0a0", font_size=22)
        title_group = VGroup(title, subtitle).arrange(DOWN, buff=0.15)
        title_group.to_edge(DOWN, buff=0.55)

        self.play(
            graph.animate.shift(UP * 0.4).scale(0.92),
            FadeIn(title_group, shift=UP * 0.2),
            run_time=1.4,
        )
        self.wait(1.8)
