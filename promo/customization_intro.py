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

# Background presets for ACT 2 — solid colours covering a range of
# moods (warm cream, deep navy, forest, lavender, sunset coral, sage).
BG_PRESETS = [
    "#fff5e6",   # cream
    "#1a1a2e",   # navy
    "#1f2e1a",   # forest
    "#e6e6fa",   # lavender
    "#f5d0a0",   # warm peach
    "#2c1a3d",   # plum
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
    # Cascade the swaps so the letters don't all change in lockstep.
    n_cycles = 5
    cycle_duration = 0.42
    for cycle in range(n_cycles):
        anims = []
        for m in letter_mobs:
            # np.random.choice returns a numpy.str_ which Pango rejects;
            # cast back to plain str before passing through manim.
            font = str(rng.choice(FONT_POOL_NON_DEFAULT))
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
    # Phone-shaped frame with placeholder "page" content inside.
    panel_w, panel_h = 3.8, 5.4
    frame = RoundedRectangle(
        width=panel_w + 0.18, height=panel_h + 0.18,
        corner_radius=0.32, color="#2a2a2a",
        stroke_width=2, fill_opacity=0,
    )
    page = RoundedRectangle(
        width=panel_w, height=panel_h, corner_radius=0.26,
        fill_color=BG_PRESETS[0], fill_opacity=1.0,
        stroke_width=0,
    )

    # Placeholder content — a header strip + 5 entry lines on the
    # page. Lines are a neutral grey so they read against most BG
    # presets without needing per-preset recolouring.
    content = VGroup()
    header_y = panel_h / 2 - 0.55
    header_bar = Rectangle(width=panel_w - 0.7, height=0.15,
                            fill_color="#7a7a7a", fill_opacity=0.55,
                            stroke_width=0)
    header_bar.move_to([0, header_y, 0])
    content.add(header_bar)
    for i in range(5):
        y = header_y - 0.85 - i * 0.75
        line = Rectangle(
            width=(panel_w - 0.9) - 0.5 * (i % 2),
            height=0.32,
            fill_color="#7a7a7a", fill_opacity=0.35,
            stroke_width=0,
        ).move_to([(- (0.25 * (i % 2))), y, 0])
        content.add(line)

    page_group = VGroup(frame, page, content)

    scene.play(FadeIn(page_group, shift=UP * 0.2), run_time=0.6)
    scene.wait(0.2)

    # Cycle the page bg through the presets (~0.55s each).
    for preset in BG_PRESETS:
        scene.play(page.animate.set_fill(preset, opacity=1.0),
                   run_time=0.55)

    # Caption
    cap2 = _body_text(act2_cap, size=24, italic=True, color=TEXT_DIM)
    cap2.next_to(page_group, DOWN, buff=0.5)
    scene.play(FadeIn(cap2, shift=UP * 0.15), run_time=0.5)
    scene.wait(1.0)

    scene.play(FadeOut(VGroup(page_group, cap2)), run_time=0.5)

    # ═════════════ ACT 3 ─ chart pictograms colour-cycling ═════════
    # 2×2 grid of mini chart pictograms. Each pictogram is built with
    # an initial colour, and we'll cycle their colours independently.
    initial_chart_colours = PALETTE[:4]
    heat = _mini_heatmap(initial_chart_colours[0])
    spir = _mini_spiral (initial_chart_colours[1])
    rose = _mini_rose   (initial_chart_colours[2])
    river= _mini_river  (initial_chart_colours[3])

    charts_grid = VGroup(heat, spir, rose, river).arrange_in_grid(
        rows=2, cols=2, buff=(1.1, 0.7),   # (horiz, vert) buffers
    )
    charts_grid.move_to(ORIGIN + UP * 0.2)

    scene.play(
        LaggedStart(*[FadeIn(c, scale=0.85) for c in charts_grid],
                    lag_ratio=0.12),
        run_time=0.9,
    )
    scene.wait(0.2)

    # Cycle each chart's colour every ~1 s, staggered.
    chart_mobs = [heat, spir, rose, river]
    for cycle in range(4):
        anims = []
        for chart in chart_mobs:
            new_colour = PALETTE[int(rng.integers(0, len(PALETTE)))]
            anims.append(chart.animate.set_color(new_colour))
        scene.play(LaggedStart(*anims, lag_ratio=0.15), run_time=1.1)

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

    # ─ middle: shrunken page mock-up
    mini_panel = page_group.copy()
    mini_panel[1].set_fill(BG_PRESETS[2], opacity=1.0)   # set a colour
    mini_panel.scale(0.50)

    # ─ right: charts grid, smaller
    mini_charts = VGroup(
        _mini_heatmap(PALETTE[0]),
        _mini_spiral (PALETTE[1]),
        _mini_rose   (PALETTE[2]),
        _mini_river  (PALETTE[3]),
    ).arrange_in_grid(rows=2, cols=2, buff=(0.4, 0.3))
    mini_charts.scale(0.55)

    outro_row = VGroup(sample_letters, mini_panel, mini_charts).arrange(
        RIGHT, buff=1.1)
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
