"""Promo motion graphics — AI Psychologist intro (~22 s, 1080p).

The visual story of what makes the AI Psychologist different from a
generic chat model: every answer is grounded in the user's real diary
through four layers of memory.

    user question types out in the chat bubble
        → 4 memory layers fade in on the left
          (raw entries → embeddings → summaries → psychological profile —
           exactly what memory.py actually stores)
            → each layer activates in turn and emits a fragment of data
              (a card, a dot, a tag) that flies into the answer area
                → AI response materialises, character by character
                    → the bits the model quoted from the diary are
                      tinted amber so it's visually obvious they came
                      from real entries
                        → privacy reminder: everything stays on device
                            → title

Render:
    manim -qh promo/ai_psychologist_intro.py AIPsychologistIntro
    manim -qh promo/ai_psychologist_intro.py AIPsychologistIntroEN
    # output → media/videos/ai_psychologist_intro/1080p60/<class>.mp4
"""
from manim import *
import numpy as np


# Visual language — matches the Neural Map promo for consistency.
BG = "#0a0a0a"
BRAND = "#009AFA"
HIGHLIGHT = "#FFD24A"      # quoted fragments lifted from real entries
PRIVACY_GREY = "#888888"

# Layer palette: bottom (raw entries) → top (psychological profile).
# Chosen so each layer feels distinct against the dark background.
LAYER_COLORS = [
    "#D9C49E",   # 1. Entries — parchment / cream
    "#009AFA",   # 2. Embeddings — brand cyan
    "#7DC36A",   # 3. Summaries — leaf green
    "#E14F88",   # 4. Psychological profile — rose
]

# Y centres of the 4 layers (bottom → top), x is the same for all.
LAYER_YS = [-1.8, -0.55, 0.7, 1.95]
LAYER_X = -4.5
LAYER_WIDTH = 5.0
LAYER_HEIGHT = 0.85


# ── Language packs ────────────────────────────────────────────────
LAYER_NAMES_RU = ["Записи", "Эмбеддинги", "Сводки", "Психологический профиль"]
QUESTION_RU = "Почему я в последнее время устаю?"
ANSWER_RU = (
    "За последние два месяца ты часто упоминал «опять никуда не успеваю»\n"
    "и «перерабатываю». Похоже, есть устойчивое чувство гонки против\n"
    "времени. Что для тебя сейчас важнее всего отпустить?"
)
HIGHLIGHTS_RU = ["«опять никуда не успеваю»", "«перерабатываю»"]
PRIVACY_RU = "всё считается на твоём устройстве"
TITLE_RU    = "AI-психолог"
SUBTITLE_RU = "локально, заземлён на твой реальный дневник"

LAYER_NAMES_EN = ["Diary entries", "Embeddings", "Summaries", "Psychological profile"]
QUESTION_EN = "Why have I been so tired lately?"
ANSWER_EN = (
    "Over the past two months you've often written «I never make it»\n"
    "and «I keep overworking». There's a persistent sense of racing\n"
    "against time. What feels most important to let go of right now?"
)
HIGHLIGHTS_EN = ["«I never make it»", "«I keep overworking»"]
PRIVACY_EN = "everything runs on your device"
TITLE_EN    = "AI Psychologist"
SUBTITLE_EN = "local, grounded in your real diary"


# ── Helpers ───────────────────────────────────────────────────────

def _make_layer_rect(y, color):
    return RoundedRectangle(
        width=LAYER_WIDTH, height=LAYER_HEIGHT, corner_radius=0.12,
        fill_color=color, fill_opacity=0.10,
        stroke_color=color, stroke_opacity=0.45, stroke_width=1.0,
    ).move_to([LAYER_X, y, 0])


def _make_layer_label(y, name):
    """Italic label sits along the LEFT inside-edge of the layer rect."""
    label = Text(name, font="Times New Roman", slant=ITALIC,
                 color="#e8e8e8", font_size=15)
    # Left edge of rect = LAYER_X - LAYER_WIDTH/2.
    label.move_to([LAYER_X - LAYER_WIDTH/2 + label.width/2 + 0.18, y, 0])
    return label


def _make_layer_hints(layer_idx, y, color):
    """Visual hint inside each layer. Returns a VGroup; one of these
    sub-objects will detach later as the layer's 'fragment'."""
    hints = VGroup()
    # Hints live in the RIGHT portion of the layer (not occupied by the label).
    # Layer rect right half: from x = LAYER_X to LAYER_X + LAYER_WIDTH/2 - 0.15.
    right_start = LAYER_X + 0.15
    right_end   = LAYER_X + LAYER_WIDTH/2 - 0.2

    if layer_idx == 0:
        # Raw entries — 3 small "cards" with horizontal text-lines.
        xs = np.linspace(right_start + 0.4, right_end - 0.4, 3)
        for x in xs:
            card = RoundedRectangle(
                width=0.7, height=0.55, corner_radius=0.05,
                fill_color=color, fill_opacity=0.30,
                stroke_color=color, stroke_opacity=0.6, stroke_width=1.0,
            ).move_to([x, y, 0])
            hints.add(card)
            for dy in (0.13, 0.0, -0.13):
                hints.add(Line(
                    [x - 0.22, y + dy, 0], [x + 0.18, y + dy, 0],
                    stroke_color=color, stroke_opacity=0.55, stroke_width=1.0,
                ))
    elif layer_idx == 1:
        # Embeddings — small dot cloud.
        rng = np.random.default_rng(7)
        for _ in range(22):
            x  = rng.uniform(right_start, right_end)
            yy = y + rng.uniform(-0.30, 0.30)
            hints.add(Dot([x, yy, 0], radius=0.05, color=color, fill_opacity=0.85))
    elif layer_idx == 2:
        # Summaries — smaller cards with one line each (compressed text).
        xs = np.linspace(right_start + 0.35, right_end - 0.35, 3)
        for x in xs:
            card = RoundedRectangle(
                width=0.65, height=0.32, corner_radius=0.05,
                fill_color=color, fill_opacity=0.30,
                stroke_color=color, stroke_opacity=0.6, stroke_width=1.0,
            ).move_to([x, y, 0])
            hints.add(card)
            hints.add(Line(
                [x - 0.22, y, 0], [x + 0.22, y, 0],
                stroke_color=color, stroke_opacity=0.55, stroke_width=1.0,
            ))
    else:
        # Psychological profile — JSON-ish chip tags.
        xs = np.linspace(right_start + 0.4, right_end - 0.4, 3)
        for x in xs:
            chip = RoundedRectangle(
                width=0.75, height=0.32, corner_radius=0.15,
                fill_color=color, fill_opacity=0.40,
                stroke_color=color, stroke_opacity=0.0, stroke_width=0,
            ).move_to([x, y, 0])
            hints.add(chip)
    return hints


# ── Main scene helper ─────────────────────────────────────────────

def _render_ai_psych(scene, question, answer, highlights, privacy,
                     title, subtitle, layer_names):
    scene.camera.background_color = BG

    # ── BUILD: chat bubbles ──────────────────────────────────
    # User question — small bubble at bottom-right of frame.
    q_bubble = RoundedRectangle(
        width=5.0, height=0.75, corner_radius=0.2,
        fill_color="#262626", fill_opacity=1.0,
        stroke_color="#555555", stroke_opacity=0.6, stroke_width=1.0,
    ).move_to([2.5, -2.95, 0])
    q_text = Text(question, font="Times New Roman", color="#dddddd",
                  font_size=20)
    q_text.move_to(q_bubble.get_center())

    # AI answer — wider bubble in the upper-right area where fragments arrive.
    a_bubble = RoundedRectangle(
        width=9.0, height=2.3, corner_radius=0.2,
        fill_color="#efefef", fill_opacity=1.0, stroke_width=0,
    ).move_to([2.5, 0.85, 0])
    a_text = Text(
        answer, font="Times New Roman", color="#1a1a1a", font_size=18,
        line_spacing=0.5,
        t2c={h: HIGHLIGHT for h in highlights},
    )
    a_text.move_to(a_bubble.get_center())

    privacy_text = Text(privacy, font="Times New Roman", slant=ITALIC,
                        color=PRIVACY_GREY, font_size=16)
    privacy_text.next_to(a_bubble, DOWN, buff=0.18)

    # ── BUILD: 4 memory layers (left side) ───────────────────
    rects, labels, hints_groups = [], [], []
    for i, (y, color, name) in enumerate(zip(LAYER_YS, LAYER_COLORS, layer_names)):
        rects.append(_make_layer_rect(y, color))
        labels.append(_make_layer_label(y, name))
        hints_groups.append(_make_layer_hints(i, y, color))

    # ── BUILD: outro title ───────────────────────────────────
    title_text = Text(title, font="Times New Roman",
                      color="#ffffff", font_size=40)
    subtitle_text = Text(subtitle, font="Times New Roman", slant=ITALIC,
                         color="#a0a0a0", font_size=20)
    title_group = VGroup(title_text, subtitle_text).arrange(DOWN, buff=0.12)
    title_group.move_to([0, -3.55, 0])

    # ── ANIMATE ───────────────────────────────────────────────

    # 0–2.4 s : question bubble + the user types in
    scene.play(FadeIn(q_bubble, shift=UP * 0.2), run_time=0.55)
    scene.play(Write(q_text), run_time=1.5)
    scene.wait(0.35)

    # 2.4–4.6 s : the 4 memory layers fade in, bottom → top
    for rect, label, hints in zip(rects, labels, hints_groups):
        scene.play(
            FadeIn(rect, shift=LEFT * 0.15),
            FadeIn(label),
            FadeIn(hints, lag_ratio=0.05),
            run_time=0.45,
        )
    scene.wait(0.3)

    # 4.6–8.0 s : each layer activates and emits one fragment toward
    # the future answer location. The fragment is a copy of one of
    # the hint sub-objects (so it visually "belongs" to that layer).
    answer_target = a_bubble.get_center()
    for rect, hints, color in zip(rects, hints_groups, LAYER_COLORS):
        # Pick a single hint to send up (the first sub-object reads cleanest).
        fragment_src = hints[0]
        fragment = fragment_src.copy()
        scene.add(fragment)

        scene.play(
            rect.animate.set_fill(color, opacity=0.32),       # layer activates
            run_time=0.25,
        )
        scene.play(
            fragment.animate
                .move_to(answer_target + np.array([0, 0.1, 0]))
                .scale(0.5)
                .set_opacity(0),
            rect.animate.set_fill(color, opacity=0.10),       # layer settles back
            run_time=0.7,
        )
    scene.wait(0.3)

    # 8.0–11.5 s : answer bubble appears and the response types out
    scene.play(FadeIn(a_bubble, shift=UP * 0.15), run_time=0.55)
    scene.play(Write(a_text), run_time=2.6)
    scene.wait(0.5)

    # 11.5–13 s : privacy line
    scene.play(FadeIn(privacy_text, shift=UP * 0.1), run_time=0.6)
    scene.wait(0.7)

    # 13–15 s : compose-down + reveal title
    everything = VGroup(
        q_bubble, q_text, a_bubble, a_text, privacy_text,
        *rects, *labels, *hints_groups,
    )
    scene.play(
        everything.animate.scale(0.93).shift(UP * 0.2),
        FadeIn(title_group, shift=UP * 0.15),
        run_time=1.1,
    )
    scene.wait(1.8)


# ── Scene classes ──────────────────────────────────────────────────

class AIPsychologistIntro(Scene):
    """Russian-language AI Psychologist intro.

    Render: manim -qh promo/ai_psychologist_intro.py AIPsychologistIntro
    """
    def construct(self):
        _render_ai_psych(
            self, QUESTION_RU, ANSWER_RU, HIGHLIGHTS_RU,
            PRIVACY_RU, TITLE_RU, SUBTITLE_RU, LAYER_NAMES_RU,
        )


class AIPsychologistIntroEN(Scene):
    """English mirror of AIPsychologistIntro.

    Render: manim -qh promo/ai_psychologist_intro.py AIPsychologistIntroEN
    """
    def construct(self):
        _render_ai_psych(
            self, QUESTION_EN, ANSWER_EN, HIGHLIGHTS_EN,
            PRIVACY_EN, TITLE_EN, SUBTITLE_EN, LAYER_NAMES_EN,
        )
