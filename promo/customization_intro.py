"""Promo motion graphics — Customization module intro (~20 s, 1080p).

Four acts, each demonstrating a different axis of customisation the
module offers, then a closing title.

  1. font cycling  — "index.life" appears in Times New Roman and the
                     brand cyan, then each letter starts cycling
                     through a different font + colour with a slight
                     cascade between letters.
  2. background    — a phone-shaped page mock-up appears; the page
                     background rapidly cycles through six bundled
                     colour presets.
  3. graphics      — a 2×2 grid of chart pictograms (heatmap, spiral,
                     rose, river) cycles their accent colour every
                     ~1 s, each chart picking its own colour.
  4. outro         — all three elements share the canvas side by side
                     under the title "Кастомизация".

Render:
    manim -qh promo/customization_intro.py CustomizationIntro
    manim -qh promo/customization_intro.py CustomizationIntroEN
"""
from manim import *
import numpy as np
import math


# ── Palette ──────────────────────────────────────────────────────
BG          = "#0a0a0a"
BRAND_CYAN  = "#009AFA"
TEXT_DIM    = "#7a7a7a"
TEXT_BODY   = "#d4d4d4"
TEXT_BRIGHT = "#ffffff"
LINE        = "#3a3a3a"
LINE_BRIGHT = "#8a8a8a"

# Brand palette — also used as the cycling colour pool for letters
# and chart accents.
PALETTE = [
    BRAND_CYAN,
    "#FFA340",   # warm amber
    "#E14F88",   # rose
    "#7DC36A",   # leaf green
    "#B780E8",   # lilac
    "#FFD24A",   # mustard
    "#5DD3D3",   # mint
    "#FF6B9D",   # pink
]

# A mix of distinctly-different fonts that ship with macOS so each
# letter looks visibly different as it cycles. Times New Roman is the
# starting point (app default + brand identity).
FONT_POOL_NON_DEFAULT = [
    "Georgia",
    "Helvetica",
    "Palatino",
    "Trebuchet MS",
    "Comic Sans MS",
    "Marker Felt",
    "Chalkboard SE",
    "Snell Roundhand",
    "SignPainter",
    "Courier New",
]

# ── High-DPI text helper (same as in the other promos) ──────────
HIGH_DPI_SIZE = 36


def _high_dpi(mob_cls, s, size, **kwargs):
    target = mob_cls(s, font_size=HIGH_DPI_SIZE, **kwargs)
    target.scale(size / HIGH_DPI_SIZE)
    return target


def _body_text(s, size=17, color=TEXT_BODY, italic=False,
               font="DejaVu Serif"):
    kw = dict(font=font, color=color, line_spacing=0.55)
    if italic:
        kw["slant"] = ITALIC
    return _high_dpi(MarkupText, s, size, **kw)


# ── Mini-chart builders for ACT 3 (and the outro recap) ──────────

def _mini_heatmap(color, w=2.0, h=1.4):
    rng = np.random.default_rng(11)
    cells = VGroup()
    cols, rows = 16, 7
    cell_w = w / cols
    cell_h = h / rows
    for c in range(cols):
        for r in range(rows):
            op = 0.25 + 0.7 * rng.random()
            sq = Square(side_length=min(cell_w, cell_h) * 0.78,
                        color=color, fill_color=color,
                        fill_opacity=op, stroke_width=0)
            sq.move_to([-w/2 + (c + 0.5) * cell_w,
                         h/2 - (r + 0.5) * cell_h, 0])
            cells.add(sq)
    return cells


def _mini_spiral(color, radius=1.0):
    rng = np.random.default_rng(7)
    dots = VGroup()
    turns = 4
    for i in range(60):
        t = i / 59
        angle = -math.pi / 2 + 2 * math.pi * turns * t
        r = 0.18 + t * (radius - 0.18)
        op = 0.30 + 0.65 * rng.random()
        d = Dot(np.array([r * math.cos(angle), r * math.sin(angle), 0]),
                radius=0.03 + 0.025 * rng.random(),
                color=color, fill_opacity=op)
        dots.add(d)
    return dots


def _mini_rose(color, radius=1.0):
    petals = VGroup()
    rng = np.random.default_rng(3)
    for i in range(7):
        angle = -math.pi / 2 + (i + 0.5) * 2 * math.pi / 7
        # Stylised petal — narrow ellipse pointing outward.
        op = 0.30 + 0.65 * rng.random()
        petal = Ellipse(width=0.45, height=radius * 1.05,
                        color=color, fill_color=color,
                        fill_opacity=op, stroke_width=0)
        petal.shift(np.array([math.sin(angle) * 0,  # pivot at origin
                              0, 0]))
        # Rotate so the long axis points outward at `angle`.
        petal.shift(UP * radius * 0.55)
        petal.rotate(angle + math.pi / 2, about_point=ORIGIN)
        petals.add(petal)
    return petals


def _mini_river(color, w=2.0, h=1.4):
    rng = np.random.default_rng(5)
    # Smooth wave + scattered raw dots underneath.
    pts = []
    n = 80
    for i in range(n):
        x = -w/2 + i / (n - 1) * w
        y = (h/2 - 0.2) * math.sin(2 * math.pi * i / (n - 1)) * 0.55
        y += 0.05 * math.sin(8 * math.pi * i / (n - 1))   # tiny ripple
        pts.append(np.array([x, y, 0]))
    line = VMobject(stroke_color=color, stroke_width=2.2,
                    stroke_opacity=0.95)
    line.set_points_smoothly(pts)

    raw = VGroup()
    for i in range(40):
        x = -w/2 + rng.random() * w
        # Pick a y near the wave at that x.
        idx = int((x + w/2) / w * (n - 1))
        y = pts[idx][1] + rng.uniform(-0.18, 0.18)
        raw.add(Dot([x, y, 0], radius=0.024,
                    color=color, fill_opacity=0.40))
    return VGroup(raw, line)


def _mini_rhythm(color, w=2.0, h=1.4):
    """7×12 weekday-month heatmap pictogram — uniform-ish grid with
    cells varying in opacity to suggest a weekday × month pattern."""
    cells = VGroup()
    cols, rows = 12, 7
    cell_w = w / cols
    cell_h = h / rows
    for r in range(rows):
        for c in range(cols):
            # Smooth gradient + slight wave so the cells differ but
            # the overall look reads as a weekday-by-month grid.
            op = 0.25 + 0.55 * (
                0.5 + 0.5 * math.sin(c * 0.45 + r * 0.6)
            )
            sq = Square(side_length=min(cell_w, cell_h) * 0.82,
                        color=color, fill_color=color,
                        fill_opacity=op, stroke_width=0)
            sq.move_to([-w/2 + (c + 0.5) * cell_w,
                         h/2 - (r + 0.5) * cell_h, 0])
            cells.add(sq)
    return cells


def _mini_ridgeline(color, w=2.2, h=1.6):
    """Stacked density curves (joyplot) — 6 horizontal silhouettes."""
    layers = VGroup()
    n_layers = 6
    rng = np.random.default_rng(19)
    for i in range(n_layers):
        baseline_y = h/2 - (i + 0.5) * (h / (n_layers + 0.5))
        n_pts = 40
        # Each ridge: sum of 2-3 gaussian bumps at random positions.
        bumps = [(rng.uniform(0.1, 0.9), rng.uniform(0.15, 0.30))
                  for _ in range(3)]
        path_pts = []
        for k in range(n_pts):
            t = k / (n_pts - 1)
            x = -w/2 + t * w
            y_val = 0
            for centre, peak in bumps:
                sigma = 0.13
                y_val += peak * math.exp(-((t - centre) / sigma) ** 2)
            y_val = min(y_val, 0.32)
            path_pts.append(np.array([x, baseline_y + y_val, 0]))
        # Close path back to baseline so we can fill it.
        path_pts.append(np.array([w/2, baseline_y, 0]))
        path_pts.append(np.array([-w/2, baseline_y, 0]))
        ridge = VMobject(stroke_color=color, stroke_width=1.0,
                          fill_color=color, fill_opacity=0.22)
        ridge.set_points_as_corners(path_pts)
        layers.add(ridge)
    return layers


def _mini_words(color, w=2.0, h=1.5):
    """Horizontal bars centred on a vertical midline — lifts go right,
    drags go left, like the actual /graphics/words chart."""
    out = VGroup()
    # Central midline
    out.add(Line(np.array([0, h/2, 0]), np.array([0, -h/2, 0]),
                  stroke_color=color, stroke_width=0.8,
                  stroke_opacity=0.45))
    rng = np.random.default_rng(29)
    n = 6
    row_h = h / (n + 1)
    for i in range(n):
        y = h/2 - (i + 1) * row_h
        is_right = i < 3
        length = rng.uniform(0.35, 0.92) * (w/2)
        bar_h = row_h * 0.55
        op = 0.45 + rng.uniform(-0.1, 0.25)
        rect = Rectangle(
            width=length, height=bar_h,
            color=color, fill_color=color, fill_opacity=op,
            stroke_width=0,
        )
        if is_right:
            rect.move_to([length / 2, y, 0])
        else:
            rect.move_to([-length / 2, y, 0])
        out.add(rect)
    return out


def _mini_activities(color, radius=0.95):
    """Packed circles — one large parent with kids on the left, a few
    standalones on the right. Mirrors the /graphics/activities card."""
    rng = np.random.default_rng(31)
    out = VGroup()
    parent = Circle(radius=radius * 0.62, color=color, fill_color=color,
                     fill_opacity=0.22, stroke_color=color,
                     stroke_opacity=0.55, stroke_width=0.7)
    parent.shift(LEFT * radius * 0.35)
    out.add(parent)
    # Children inside the parent
    for _ in range(5):
        ang = rng.uniform(0, 2 * math.pi)
        rr = rng.uniform(0, radius * 0.32)
        x = parent.get_center()[0] + rr * math.cos(ang)
        y = parent.get_center()[1] + rr * math.sin(ang)
        sz = rng.uniform(0.06, 0.13)
        out.add(Dot([x, y, 0], radius=sz, color=color,
                     fill_opacity=0.30 + rng.uniform(0, 0.4)))
    # Standalone circles on the right
    for pos in [(radius*0.5, radius*0.35),
                (radius*0.75, -radius*0.30),
                (radius*0.40, -radius*0.65)]:
        sz = rng.uniform(0.13, 0.22)
        out.add(Circle(radius=sz, color=color, fill_color=color,
                        fill_opacity=0.35 + rng.uniform(0, 0.3),
                        stroke_color=color, stroke_opacity=0.5,
                        stroke_width=0.5).shift(np.array([pos[0], pos[1], 0])))
    return out


def _mini_neural_map(color, w=2.1, h=1.5):
    """Few neurons (dot + halo) connected by faint edges — mirrors the
    deep_mind module's neural map."""
    rng = np.random.default_rng(37)
    out = VGroup()
    # Random-ish but stable neuron layout
    positions = [
        np.array([-w/2 + 0.30, h/3, 0]),
        np.array([w/2 - 0.30, h/3 - 0.05, 0]),
        np.array([0.0, -h/3 + 0.10, 0]),
        np.array([-w/4, -h/4, 0]),
        np.array([w/3, -h/3, 0]),
        np.array([w/8, h/8, 0]),
    ]
    # Edges first (so neurons sit on top)
    edges = [(0,1), (0,2), (1,2), (2,3), (2,4), (3,4), (5,1), (5,0), (5,3)]
    for a, b in edges:
        out.add(Line(positions[a], positions[b],
                      stroke_color=color, stroke_width=0.7,
                      stroke_opacity=0.40))
    # Neurons: halo + body
    for pos in positions:
        halo_r = 0.18 + rng.uniform(0, 0.04)
        out.add(Circle(radius=halo_r, color=color, fill_color=color,
                        fill_opacity=0.16, stroke_width=0).move_to(pos))
        out.add(Dot(pos, radius=0.08, color=color, fill_opacity=0.95))
    return out


# ── Text packs ───────────────────────────────────────────────────
INDEX_LIFE       = "index.life"
ACT1_CAP_RU      = "Кастомизируй шрифт"
ACT2_CAP_RU      = "Кастомизируй фон"
ACT3_CAP_RU      = "Кастомизируй графики"
TITLE_RU         = "Кастомизация"
SUBTITLE_RU      = "Кастомизируй index"

ACT1_CAP_EN      = "Customise the font"
ACT2_CAP_EN      = "Customise the background"
ACT3_CAP_EN      = "Customise the charts"
TITLE_EN         = "Customisation"
SUBTITLE_EN      = "Make index yours"


# ── Main scene helper ────────────────────────────────────────────

def _render_customization(scene: Scene, *, act1_cap, act2_cap, act3_cap,
                          title_text, subtitle_text):
    scene.camera.background_color = BG
    rng = np.random.default_rng(23)

    # ═════════════ ACT 1 ─ font cycling on "index.life" ════════════
    # Build one Text mob per letter at the brand default (Times +
    # cyan). Arrange horizontally, centred.
    letter_mobs = []
    for ch in INDEX_LIFE:
        m = _high_dpi(Text, ch, 64, font="Times New Roman",
                      color=BRAND_CYAN)
        letter_mobs.append(m)
    letters = VGroup(*letter_mobs).arrange(RIGHT, buff=0.06)
    letters.move_to(ORIGIN + UP * 0.3)

    scene.play(FadeIn(letters, shift=DOWN * 0.2), run_time=0.7)
    scene.wait(0.4)

    # Cycle each letter through several (font, colour) variants.
    # Per-letter shuffled font sequences guarantee no letter ever gets
    # the same font twice in a row — drawing fresh from rng.choice each
    # time produced pathological runs like "x → Helvetica → Helvetica
    # → Helvetica" with the wrong seed, making one letter look stuck
    # while the rest danced.
    n_cycles = 5
    cycle_duration = 0.60
    letter_font_seqs: list[list[str]] = []
    for _ in letter_mobs:
        pool = list(FONT_POOL_NON_DEFAULT)
        rng.shuffle(pool)
        letter_font_seqs.append(pool)

    for cycle in range(n_cycles):
        anims = []
        for i, m in enumerate(letter_mobs):
            font = letter_font_seqs[i][cycle % len(letter_font_seqs[i])]
            colour = PALETTE[int(rng.integers(1, len(PALETTE)))]
            replacement = _high_dpi(Text, m.text, 64,
                                    font=font, color=colour)
            replacement.move_to(m.get_center())
            anims.append(Transform(m, replacement))
        scene.play(LaggedStart(*anims, lag_ratio=0.04),
                   run_time=cycle_duration)

    # Caption appears beneath the cycling letters.
    cap1 = _body_text(act1_cap, size=24, italic=True, color=TEXT_DIM)
    cap1.next_to(letters, DOWN, buff=0.9)
    scene.play(FadeIn(cap1, shift=UP * 0.15), run_time=0.5)
    scene.wait(1.2)

    # Fade ACT 1 out
    scene.play(FadeOut(VGroup(letters, cap1)), run_time=0.5)

    # ═════════════ ACT 2 ─ page background cycling ═════════════════
    # Real app screenshots from promo/customization_assets/{1..12}.png,
    # each capturing the same page with a different bg preset. We
    # crossfade through them so the user sees the actual UI mutate
    # rather than an abstract phone mock-up.
    from pathlib import Path
    assets = Path(__file__).resolve().parent / "customization_assets"
    screenshot_paths = sorted(
        assets.glob("*.png"),
        key=lambda p: int(p.stem) if p.stem.isdigit() else p.stem,
    )
    screenshots: list[ImageMobject] = []
    for path in screenshot_paths:
        img = ImageMobject(str(path))
        img.scale_to_fit_width(9.0)     # ~63% of the 14.2-unit frame width
        img.move_to(ORIGIN + UP * 0.30)
        screenshots.append(img)

    # First frame fades in; subsequent frames crossfade. We use
    # FadeOut + FadeIn rather than .animate.set_opacity(...) — on
    # ImageMobject the .animate path only renders cleanly for the
    # first couple of swaps and then stalls (images 4..12 silently
    # never appear). FadeOut/FadeIn handle the remove + add + opacity
    # reset internally and stay correct across all twelve transitions.
    scene.play(FadeIn(screenshots[0]), run_time=0.6)
    scene.wait(0.45)
    for prev, cur in zip(screenshots, screenshots[1:]):
        scene.play(FadeOut(prev), FadeIn(cur), run_time=0.55)
    last_screenshot = screenshots[-1]

    cap2 = _body_text(act2_cap, size=24, italic=True, color=TEXT_DIM)
    cap2.next_to(last_screenshot, DOWN, buff=0.40)
    scene.play(FadeIn(cap2, shift=UP * 0.15), run_time=0.5)
    scene.wait(1.0)

    scene.play(FadeOut(last_screenshot), FadeOut(cap2), run_time=0.5)

    # ═════════════ ACT 3 ─ chart pictograms colour-cycling ═════════
    # 3×3 grid covering every customisable chart in the app:
    #   heatmap · spiral · rose
    #   rhythm  · ridgeline · words
    #   river   · activities · neural map
    # Each pictogram is a VGroup with a single accent colour we can
    # cycle independently.
    chart_builders = [
        _mini_heatmap, _mini_spiral, _mini_rose,
        _mini_rhythm, _mini_ridgeline, _mini_words,
        _mini_river, _mini_activities, _mini_neural_map,
    ]
    chart_mobs = []
    for i, builder in enumerate(chart_builders):
        chart_mobs.append(builder(PALETTE[i % len(PALETTE)]))

    charts_grid = VGroup(*chart_mobs).arrange_in_grid(
        rows=3, cols=3, buff=(0.55, 0.40),
    )
    # The neural-map / activities / ridgeline minis are taller than the
    # heatmap; scale the whole grid to a uniform height that fits above
    # the caption at y = -3.2.
    charts_grid.scale_to_fit_height(4.6)
    charts_grid.move_to(ORIGIN + UP * 0.30)

    scene.play(
        LaggedStart(*[FadeIn(c, scale=0.85) for c in charts_grid],
                    lag_ratio=0.07),
        run_time=1.1,
    )
    scene.wait(0.2)

    # Cycle each chart's colour every ~1.1 s, staggered.
    for cycle in range(4):
        anims = []
        for chart in chart_mobs:
            new_colour = PALETTE[int(rng.integers(0, len(PALETTE)))]
            anims.append(chart.animate.set_color(new_colour))
        scene.play(LaggedStart(*anims, lag_ratio=0.08), run_time=1.1)

    cap3 = _body_text(act3_cap, size=24, italic=True, color=TEXT_DIM)
    cap3.next_to(charts_grid, DOWN, buff=0.6)
    scene.play(FadeIn(cap3, shift=UP * 0.15), run_time=0.5)
    scene.wait(0.8)

    scene.play(FadeOut(VGroup(charts_grid, cap3)), run_time=0.5)

    # ═════════════ ACT 4 ─ outro: all three side-by-side + title ════
    # Mini font sample on the left, mini page in the middle, mini
    # chart grid on the right. Title + subtitle below.
    # ─ left: a few sample letters in distinct fonts/colours
    sample_fonts  = ["Comic Sans MS", "Snell Roundhand", "Marker Felt",
                     "Georgia"]
    sample_letters = VGroup()
    for i, ch in enumerate(["A", "a", "Я", "b"]):
        m = _high_dpi(Text, ch, 44, font=sample_fonts[i],
                      color=PALETTE[i])
        sample_letters.add(m)
    sample_letters.arrange(RIGHT, buff=0.15)

    # ─ middle: shrunken real screenshot (pick a vivid one from the bg
    # cycle so the recap actually shows the kind of customisation the
    # promo just demonstrated).
    if screenshot_paths:
        recap_path = screenshot_paths[len(screenshot_paths) // 2]
        mini_panel = ImageMobject(str(recap_path))
        mini_panel.scale_to_fit_width(3.4)
    else:
        # Defensive fallback if assets dir is empty
        mini_panel = RoundedRectangle(
            width=3.4, height=2.1, corner_radius=0.18,
            color="#3a3a3a", stroke_width=2, fill_opacity=0,
        )

    # ─ right: charts grid, smaller
    mini_charts = VGroup(
        _mini_heatmap(PALETTE[0]),
        _mini_spiral (PALETTE[1]),
        _mini_rose   (PALETTE[2]),
        _mini_river  (PALETTE[3]),
    ).arrange_in_grid(rows=2, cols=2, buff=(0.4, 0.3))
    mini_charts.scale(0.55)

    # Use Group (not VGroup) since ImageMobject isn't a VMobject — mixing
    # types in a VGroup would crash at arrange time.
    outro_row = Group(sample_letters, mini_panel, mini_charts).arrange(
        RIGHT, buff=0.75)
    outro_row.move_to(ORIGIN + UP * 0.55)

    title = _high_dpi(Text, title_text, 46, font="DejaVu Serif",
                      color=TEXT_BRIGHT)
    subtitle = _body_text(subtitle_text, size=22, italic=True,
                          color="#9a9a9a")
    title_group = VGroup(title, subtitle).arrange(DOWN, buff=0.18)
    title_group.next_to(outro_row, DOWN, buff=0.55)

    scene.play(
        FadeIn(outro_row, shift=UP * 0.2),
        run_time=0.9,
    )
    scene.play(FadeIn(title_group, shift=UP * 0.2), run_time=0.7)
    scene.wait(2.4)


# ── Scene classes ─────────────────────────────────────────────────

class CustomizationIntro(Scene):
    """Russian-language Customisation module intro.

    Render: manim -qh promo/customization_intro.py CustomizationIntro
    """
    def construct(self):
        _render_customization(
            self,
            act1_cap=ACT1_CAP_RU,
            act2_cap=ACT2_CAP_RU,
            act3_cap=ACT3_CAP_RU,
            title_text=TITLE_RU,
            subtitle_text=SUBTITLE_RU,
        )


class CustomizationIntroEN(Scene):
    """English mirror.

    Render: manim -qh promo/customization_intro.py CustomizationIntroEN
    """
    def construct(self):
        _render_customization(
            self,
            act1_cap=ACT1_CAP_EN,
            act2_cap=ACT2_CAP_EN,
            act3_cap=ACT3_CAP_EN,
            title_text=TITLE_EN,
            subtitle_text=SUBTITLE_EN,
        )
