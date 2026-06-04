"""Promo motion graphics — Graphics module intro (~22 s, 1080p).

Black canvas; a single year of mood-diary entries (~300 dots, one per
recorded day, opacity coded by the day's mood rating) morphs through
four of the module's visualisations in turn:

    1. heatmap calendar   — the year as a 7×52 rectangular grid
                            (one cell per day, shaded by mood).
    2. spiral year        — the same year wound into a spiral, the
                            day's angle and radius derived from its
                            day-of-year.
    3. weekday rose       — seven petal sectors (one per weekday);
                            inside each sector, the dots cluster
                            radially by rating.
    4. mood river         — time on x, rating on y — the dots trace
                            the year's mood curve directly.

Each dot keeps its identity (the same diary entry) through every
transition — that's the whole story: same data, many views. After
the river, the title fades in.

A 5th approach (modify-manim-source via TEXT_MOB_SCALE_FACTOR) was
considered but the `_high_dpi` wrapper used by the other promos is
enough.

Render:
    manim -qh promo/graphics_intro.py GraphicsIntro
    manim -qh promo/graphics_intro.py GraphicsIntroEN
"""
from manim import *
import numpy as np
import math


# ── Palette ──────────────────────────────────────────────────────
BG          = "#0a0a0a"
DOT_COLOR   = "#FFD24A"    # mustard — same as the data accents in the
                            # other promos
LINE        = "#3a3a3a"
LINE_BRIGHT = "#8a8a8a"
TEXT_DIM    = "#7a7a7a"
TEXT_BODY   = "#d4d4d4"
TEXT_BRIGHT = "#ffffff"


# ── High-DPI text helper (same as in ai_psychologist_intro) ──────
HIGH_DPI_SIZE = 36


def _high_dpi(mob_cls, s, size, **kwargs):
    target = mob_cls(s, font_size=HIGH_DPI_SIZE, **kwargs)
    target.scale(size / HIGH_DPI_SIZE)
    return target


def _body_text(s, size=17, color=TEXT_BODY, italic=False):
    kw = dict(font="DejaVu Serif", color=color, line_spacing=0.55)
    if italic:
        kw["slant"] = ITALIC
    return _high_dpi(MarkupText, s, size, **kw)


# ── Data generation ──────────────────────────────────────────────

def _generate_year(rng):
    """Return a list of (day_of_year, rating, jitter_a, jitter_b)
    tuples for ~310 days of the year — most days have an entry, ~15%
    are skipped so it looks like a real diary. The rating follows a
    sinusoidal seasonal pattern (peak in mid-summer, trough in late
    winter) plus Gaussian noise; jitter_a/_b are stable per-entry
    random offsets used by the rose + scatter positions so a single
    dot doesn't jump around during transitions.
    """
    entries = []
    for d in range(1, 366):
        if rng.random() < 0.12:
            continue
        seasonal = 5.5 + 1.8 * math.sin(2 * math.pi * (d - 80) / 365)
        noise = rng.normal(0, 1.0)
        rating = max(1, min(10, int(round(seasonal + noise))))
        jitter_a = rng.uniform(-1.0, 1.0)
        jitter_b = rng.uniform(-1.0, 1.0)
        entries.append((d, rating, jitter_a, jitter_b))
    return entries


# ── Position computers — one function per visualisation ──────────

def _scatter_positions(data):
    """Random-feeling cloud across the canvas — the opening state."""
    out = []
    for _d, _r, ja, jb in data:
        out.append(np.array([ja * 5.5, jb * 2.6, 0]))
    return out


def _heatmap_positions(data):
    """7 rows × ~52 columns calendar grid, centred on the canvas."""
    cell_w = 0.13
    cell_h = 0.42
    weeks = 53
    x0 = -weeks * cell_w / 2 + cell_w / 2
    y0 = (7 * cell_h) / 2 - cell_h / 2
    out = []
    for d, _r, _ja, _jb in data:
        weekday = (d - 1) % 7
        week = (d - 1) // 7
        x = x0 + week * cell_w
        y = y0 - weekday * cell_h
        out.append(np.array([x, y, 0]))
    return out


def _spiral_positions(data):
    """One spiral covering the year with 4 turns — wide enough that
    individual dots stay legible, tight enough to read as a spiral."""
    cx, cy = 0.0, 0.0
    r_min, r_max = 0.45, 2.65
    turns = 4
    out = []
    for d, _r, _ja, _jb in data:
        t = (d - 1) / 364
        angle = -math.pi / 2 + 2 * math.pi * turns * t
        r = r_min + t * (r_max - r_min)
        out.append(np.array([cx + r * math.cos(angle),
                             cy + r * math.sin(angle), 0]))
    return out


def _rose_positions(data):
    """7 weekday sectors radiating from the centre. Within each sector
    angles are stably jittered (so a dot doesn't twitch between
    renders) and radius grows with the rating."""
    cx, cy = 0.0, 0.0
    inner_r, outer_r = 0.4, 2.75
    sector_w = (2 * math.pi / 7) * 0.78  # leave gaps between petals
    out = []
    for d, r, ja, _jb in data:
        weekday = (d - 1) % 7
        sector_centre = -math.pi / 2 + (weekday + 0.5) * 2 * math.pi / 7
        angle = sector_centre + ja * sector_w / 2
        # Rating maps to a position along the petal radius, plus a
        # tiny radial jitter so dots at the same rating don't pile up.
        radius = inner_r + ((r - 1) / 9) * (outer_r - inner_r) * 0.95
        radius += _jb * 0.08
        out.append(np.array([cx + radius * math.cos(angle),
                             cy + radius * math.sin(angle), 0]))
    return out


def _river_positions(data):
    """Time on x (Jan→Dec), rating on y (high mood up)."""
    x_left, x_right = -5.0, 5.0
    y_lo,   y_hi    = -1.8,  2.0
    out = []
    for d, r, _ja, jb in data:
        x = x_left + (d - 1) / 364 * (x_right - x_left)
        y = y_lo + (r - 1) / 9 * (y_hi - y_lo)
        # A small vertical jitter so days with the same rating don't
        # stack into a flat band — keeps the wave feeling natural.
        y += jb * 0.05
        out.append(np.array([x, y, 0]))
    return out


# ── Structural overlays — axes, gridlines, labels, guide curves.
# Each visualisation gets one VGroup that fades in with the morph and
# fades out when the dots leave for the next phase. Without these the
# dots just form abstract shapes; with them the structure of each
# chart is legible.

# January-1 of a non-leap year (Jan 1 == Monday for our synthetic data)
MONTH_STARTS_DAY = [1, 32, 60, 91, 121, 152, 182, 213, 244, 274, 305, 335]


def _build_heatmap_struct():
    """Heatmap calendar overlay: month numbers above the grid."""
    cell_w = 0.13
    weeks = 53
    x0 = -weeks * cell_w / 2 + cell_w / 2
    y_label = (7 * 0.42) / 2 + 0.45
    labels = VGroup()
    for m, day in enumerate(MONTH_STARTS_DAY):
        week = (day - 1) // 7
        x = x0 + week * cell_w
        t = _high_dpi(Text, f"{m+1:02d}", 11,
                      font="Helvetica", color=TEXT_DIM)
        t.move_to([x, y_label, 0])
        labels.add(t)
    return labels


def _build_spiral_struct():
    """Spiral overlay: faint guide curve along the dot path + 12
    month markers at the angle where each month begins."""
    cx, cy = 0.0, 0.0
    r_min, r_max = 0.45, 2.65
    turns = 4

    # Faint guide spiral — sample 200 points along the path.
    guide_pts = []
    for i in range(201):
        t = i / 200
        angle = -math.pi / 2 + 2 * math.pi * turns * t
        r = r_min + t * (r_max - r_min)
        guide_pts.append(np.array([cx + r * math.cos(angle),
                                   cy + r * math.sin(angle), 0]))
    guide = VMobject(stroke_color=LINE_BRIGHT, stroke_width=0.8,
                     stroke_opacity=0.30)
    guide.set_points_smoothly(guide_pts)

    # 12 month markers at the spiral position where each month begins,
    # nudged slightly outward so the label doesn't sit on a dot.
    labels = VGroup()
    for m, day in enumerate(MONTH_STARTS_DAY):
        t = (day - 1) / 364
        angle = -math.pi / 2 + 2 * math.pi * turns * t
        r = r_min + t * (r_max - r_min) + 0.30
        x = cx + r * math.cos(angle)
        y = cy + r * math.sin(angle)
        label = _high_dpi(Text, f"{m+1:02d}", 10,
                          font="Helvetica", color=TEXT_DIM)
        label.move_to([x, y, 0])
        labels.add(label)

    return VGroup(guide, labels)


def _build_rose_struct(weekday_names):
    """Rose overlay: three concentric reference rings + seven weekday
    labels positioned outside the petals."""
    cx, cy = 0.0, 0.0
    inner_r, outer_r = 0.4, 2.75
    label_r = outer_r + 0.30

    rings = VGroup()
    for r in [inner_r, (inner_r + outer_r) / 2, outer_r]:
        ring = Circle(radius=r, stroke_color=LINE_BRIGHT,
                      stroke_width=0.6, stroke_opacity=0.25,
                      fill_opacity=0)
        ring.move_to([cx, cy, 0])
        rings.add(ring)

    labels = VGroup()
    for i, name in enumerate(weekday_names):
        angle = -math.pi / 2 + (i + 0.5) * 2 * math.pi / 7
        x = cx + label_r * math.cos(angle)
        y = cy + label_r * math.sin(angle)
        label = _high_dpi(Text, name, 12, font="Helvetica", color=TEXT_DIM)
        label.move_to([x, y, 0])
        labels.add(label)

    return VGroup(rings, labels)


def _build_river_struct(data):
    """River overlay: x-axis with month numbers, y-axis with 1/5/10
    ticks + dashed gridlines, plus a 14-day smoothed trend line drawn
    over the dots so the underlying curve is obvious."""
    x_left, x_right = -5.0, 5.0
    y_lo,   y_hi    = -1.8,  2.0

    elements = VGroup()

    # X-axis baseline + month tick labels at month-start positions
    baseline = Line(np.array([x_left, y_lo - 0.10, 0]),
                    np.array([x_right, y_lo - 0.10, 0]),
                    stroke_color=LINE_BRIGHT, stroke_width=0.8,
                    stroke_opacity=0.6)
    elements.add(baseline)
    for m, day in enumerate(MONTH_STARTS_DAY):
        x = x_left + (day - 1) / 364 * (x_right - x_left)
        label = _high_dpi(Text, f"{m+1:02d}", 10,
                          font="Helvetica", color=TEXT_DIM)
        label.move_to([x, y_lo - 0.35, 0])
        elements.add(label)

    # Y-axis: rating ticks at 1, 5, 10 + dashed horizontal gridlines
    for rating in (1, 5, 10):
        y = y_lo + (rating - 1) / 9 * (y_hi - y_lo)
        grid = DashedLine(np.array([x_left, y, 0]),
                          np.array([x_right, y, 0]),
                          stroke_color=LINE, stroke_width=0.5,
                          stroke_opacity=0.4, dash_length=0.08)
        elements.add(grid)
        label = _high_dpi(Text, str(rating), 10,
                          font="Helvetica", color=TEXT_DIM)
        label.move_to([x_left - 0.35, y, 0])
        elements.add(label)

    # 14-day moving average over the year → trend line.
    by_day = {d: r for d, r, *_ in data}
    smoothed = []
    for day in range(1, 366):
        window = [by_day[k] for k in range(max(1, day - 7),
                                            min(366, day + 8))
                  if k in by_day]
        if window:
            avg = sum(window) / len(window)
            x = x_left + (day - 1) / 364 * (x_right - x_left)
            y = y_lo + (avg - 1) / 9 * (y_hi - y_lo)
            smoothed.append(np.array([x, y, 0]))
    trend = VMobject(stroke_color="#ffffff", stroke_width=2.0,
                     stroke_opacity=0.85)
    trend.set_points_smoothly(smoothed)
    elements.add(trend)

    return elements


# ── Russian / English text packs ─────────────────────────────────

TITLE_RU    = "Графики"
SUBTITLE_RU = "Твоё настроение, нарисованное с разных ракурсов"
LABELS_RU = {
    "heatmap": "Обзор · весь год одной картинкой",
    "spiral":  "Спираль года",
    "rose":    "Роза недели",
    "river":   "Река настроения",
}
WEEKDAYS_RU = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"]

TITLE_EN    = "Graphics"
SUBTITLE_EN = "Your mood, drawn from different angles"
LABELS_EN = {
    "heatmap": "Overview · the whole year at a glance",
    "spiral":  "Year as a spiral",
    "rose":    "Weekday rose",
    "river":   "Mood river",
}
WEEKDAYS_EN = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


# ── Main scene helper ────────────────────────────────────────────

def _render_graphics_intro(scene: Scene, *, title_text, subtitle_text,
                           labels, weekdays):
    scene.camera.background_color = BG
    rng = np.random.default_rng(7)
    data = _generate_year(rng)

    # Build one Dot per entry. Both opacity AND radius scale with the
    # day's mood rating so the rating is visible at a glance: a 1/10
    # day is small + dim, a 10/10 day is large + bright. Mirrors how
    # the actual heatmap / spiral encode mood in the app (light = good,
    # dark = bad, plus a size cue on the spiral page).
    def opacity_for(r):
        return 0.15 + 0.82 * (r - 1) / 9      # 0.15 .. 0.97
    def radius_for(r):
        return 0.028 + 0.044 * (r - 1) / 9    # 0.028 .. 0.072

    dots = []
    for _d, r, _ja, _jb in data:
        dot = Dot(np.array([0, 0, 0]),
                  radius=radius_for(r),
                  color=DOT_COLOR,
                  fill_opacity=opacity_for(r))
        dots.append(dot)
    dots_group = VGroup(*dots)

    # Pre-compute all five position lists once (one per phase).
    p_scatter = _scatter_positions(data)
    p_heat    = _heatmap_positions(data)
    p_spir    = _spiral_positions(data)
    p_rose    = _rose_positions(data)
    p_river   = _river_positions(data)

    # Place each dot at its scatter position so the opening reveal
    # is a cloud, not a flash from origin.
    for dot, pos in zip(dots, p_scatter):
        dot.move_to(pos)

    # Title group for the opening + closing beats.
    title    = _high_dpi(Text, title_text, 48, font="DejaVu Serif",
                         color=TEXT_BRIGHT)
    subtitle = _body_text(subtitle_text, size=22, italic=True,
                          color=TEXT_BODY)
    title_group = VGroup(title, subtitle).arrange(DOWN, buff=0.22)

    # Per-viz caption — one mobject per phase. Sits at the bottom.
    def caption(text):
        c = _body_text(text, size=20, italic=True, color=TEXT_DIM)
        c.move_to([0, -3.20, 0])
        return c

    cap_heat  = caption(labels["heatmap"])
    cap_spir  = caption(labels["spiral"])
    cap_rose  = caption(labels["rose"])
    cap_river = caption(labels["river"])

    # Structural overlays — axes / labels / guides for each chart.
    struct_heat  = _build_heatmap_struct()
    struct_spir  = _build_spiral_struct()
    struct_rose  = _build_rose_struct(weekdays)
    struct_river = _build_river_struct(data)

    # ═══════════════ ANIMATE ═══════════════════════════════════════

    # ── ACT 1 ─ title + subtitle (no dots yet)
    scene.play(FadeIn(title_group, shift=UP * 0.2), run_time=1.0)
    scene.wait(1.4)
    scene.play(FadeOut(title_group, shift=UP * 0.1), run_time=0.6)

    # ── ACT 2 ─ scatter the year of dots
    scene.play(
        LaggedStart(*[FadeIn(d, scale=0.6) for d in dots],
                    lag_ratio=0.0025),
        run_time=1.6,
    )
    scene.wait(0.3)

    # Make sure the structural overlays sit behind the dots so dot
    # bodies aren't obscured by grid lines / guide curves.
    for struct in (struct_heat, struct_spir, struct_rose, struct_river):
        struct.set_z_index(-1)
    dots_group.set_z_index(1)

    # ── ACT 3 ─ morph to heatmap (struct + caption fade in alongside)
    scene.play(
        *[d.animate.move_to(p) for d, p in zip(dots, p_heat)],
        FadeIn(struct_heat),
        FadeIn(cap_heat, shift=UP * 0.1),
        run_time=1.7, rate_func=smooth,
    )
    scene.wait(2.3)

    # ── ACT 4 ─ morph to spiral
    scene.play(
        *[d.animate.move_to(p) for d, p in zip(dots, p_spir)],
        FadeOut(struct_heat), FadeOut(cap_heat),
        FadeIn(struct_spir), FadeIn(cap_spir, shift=UP * 0.1),
        run_time=1.7, rate_func=smooth,
    )
    scene.wait(2.3)

    # ── ACT 5 ─ morph to rose
    scene.play(
        *[d.animate.move_to(p) for d, p in zip(dots, p_rose)],
        FadeOut(struct_spir), FadeOut(cap_spir),
        FadeIn(struct_rose), FadeIn(cap_rose, shift=UP * 0.1),
        run_time=1.7, rate_func=smooth,
    )
    scene.wait(2.3)

    # ── ACT 6 ─ morph to river
    scene.play(
        *[d.animate.move_to(p) for d, p in zip(dots, p_river)],
        FadeOut(struct_rose), FadeOut(cap_rose),
        FadeIn(struct_river), FadeIn(cap_river, shift=UP * 0.1),
        run_time=1.7, rate_func=smooth,
    )
    scene.wait(2.3)

    # ── OUTRO ─ shift dots + axes up + scale, drop final title underneath
    body_group = VGroup(dots_group, struct_river)
    scene.play(
        body_group.animate.shift(UP * 0.55).scale(0.85),
        FadeOut(cap_river),
        run_time=0.8,
    )
    title_group_final = VGroup(
        _high_dpi(Text, title_text, 42, font="DejaVu Serif",
                  color=TEXT_BRIGHT),
        _body_text(subtitle_text, size=20, italic=True, color="#9a9a9a"),
    ).arrange(DOWN, buff=0.18).move_to([0, -2.95, 0])
    scene.play(FadeIn(title_group_final, shift=UP * 0.2), run_time=0.8)
    scene.wait(2.0)


# ── Scene classes ─────────────────────────────────────────────────

class GraphicsIntro(Scene):
    """Russian-language Graphics module intro.

    Render: manim -qh promo/graphics_intro.py GraphicsIntro
    """
    def construct(self):
        _render_graphics_intro(
            self,
            title_text=TITLE_RU,
            subtitle_text=SUBTITLE_RU,
            labels=LABELS_RU,
            weekdays=WEEKDAYS_RU,
        )


class GraphicsIntroEN(Scene):
    """English mirror.

    Render: manim -qh promo/graphics_intro.py GraphicsIntroEN
    """
    def construct(self):
        _render_graphics_intro(
            self,
            title_text=TITLE_EN,
            subtitle_text=SUBTITLE_EN,
            labels=LABELS_EN,
            weekdays=WEEKDAYS_EN,
        )
