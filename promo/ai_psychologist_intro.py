"""Promo motion graphics — AI Psychologist intro (~20 s, 1080p).

A chat-centric promo: the viewer watches a real-feeling chat unfold.

    a clean chat panel fades in
        → the user types a question into the input box
            → on send, the text rises into a user message bubble
              (avatar + bubble, matching the real app's layout)
                → AI's avatar appears with a "typing" indicator
                    → around the chat, three diary-excerpt cards drift
                      in and converge on the AI's spot — those are the
                      very fragments the model will cite in its answer
                        → AI bubble materialises, response types in,
                          the cited quotes are tinted amber so the
                          viewer sees they came from real entries
                            → input fades, privacy line + title appear

The cards' snippets are the exact strings the answer highlights —
that's what visually proves the AI is grounded in the user's diary.

Render:
    manim -qh promo/ai_psychologist_intro.py AIPsychologistIntro
    manim -qh promo/ai_psychologist_intro.py AIPsychologistIntroEN
"""
from manim import *
import numpy as np


# ── Visual language ──────────────────────────────────────────────
BG = "#0a0a0a"
CHAT_BG = "#f7f7f7"
CHAT_BORDER = "#e2e2e2"
USER_BUBBLE_BG = "#ebebeb"
AI_BUBBLE_BG = "#ffffff"
AI_BUBBLE_BORDER = "#e0e0e0"
INPUT_BG = "#ffffff"
INPUT_BORDER = "#cccccc"

USER_AVATAR_COLOR = "#FFA340"     # warm amber, contrasts with AI cyan
AI_AVATAR_COLOR   = "#009AFA"     # brand cyan (matches in-app default)

HIGHLIGHT = "#C77F0F"             # quoted fragments (darker amber on white)
TEXT_DARK = "#1a1a1a"
TEXT_MUTED = "#6a6a6a"

# ── Layout (manim units; frame ~ -7.1..7.1 × -4..4 at 16:9) ──────
CHAT_CENTER = np.array([0, 0.05, 0])
CHAT_W, CHAT_H = 10.0, 6.0

USER_AVATAR_POS  = np.array([ 4.05,  1.80, 0])
USER_BUBBLE_CTR  = np.array([ 0.90,  1.80, 0])
USER_BUBBLE_W, USER_BUBBLE_H = 5.5, 0.75

AI_AVATAR_POS    = np.array([-4.05, -0.65, 0])
AI_BUBBLE_CTR    = np.array([ 0.95, -0.65, 0])
AI_BUBBLE_W, AI_BUBBLE_H = 8.0, 2.45

INPUT_CTR        = np.array([0,    -2.45, 0])
INPUT_W, INPUT_H = 8.8, 0.75

# Card start positions — around the chat, outside its right/left edges.
CARD_START_POSITIONS = [
    np.array([ 6.4,  2.6, 0]),   # top-right (outside)
    np.array([-6.4,  1.4, 0]),   # left
    np.array([-6.4, -2.3, 0]),   # bottom-left (outside)
]


# ── Language packs ────────────────────────────────────────────────
QUESTION_RU = "Почему я в последнее время устаю?"
ANSWER_RU = (
    "За последние два месяца ты часто упоминал «опять никуда не успеваю»\n"
    "и «перерабатываю». Похоже, есть устойчивое чувство гонки против\n"
    "времени. Что для тебя сейчас важнее всего отпустить?"
)
HIGHLIGHTS_RU = ["«опять никуда не успеваю»", "«перерабатываю»"]
DIARY_CARDS_RU = [
    ("12 марта",  "«опять никуда не успеваю»"),
    ("5 апреля",  "«снова перерабатываю»"),
    ("21 апреля", "гонка против времени"),
]
INPUT_HINT_RU = "Сообщение…"
PRIVACY_RU = "всё считается на твоём устройстве"
TITLE_RU = "AI-психолог"
SUBTITLE_RU = "локально, заземлён на твой реальный дневник"

QUESTION_EN = "Why have I been so tired lately?"
ANSWER_EN = (
    "Over the past two months you've often written «I never make it»\n"
    "and «I keep overworking». There's a persistent sense of racing\n"
    "against time. What feels most important to let go of right now?"
)
HIGHLIGHTS_EN = ["«I never make it»", "«I keep overworking»"]
DIARY_CARDS_EN = [
    ("Mar 12", "«I never make it»"),
    ("Apr 5",  "«I keep overworking»"),
    ("Apr 21", "race against time"),
]
INPUT_HINT_EN = "Message…"
PRIVACY_EN = "everything runs on your device"
TITLE_EN = "AI Psychologist"
SUBTITLE_EN = "local, grounded in your real diary"


# ── Builders ─────────────────────────────────────────────────────

def _chat_container():
    """The light card that holds the whole chat. Drop-shadow faked
    with a second slightly-offset rect behind it."""
    shadow = RoundedRectangle(
        width=CHAT_W + 0.08, height=CHAT_H + 0.08, corner_radius=0.28,
        fill_color="#000000", fill_opacity=0.35, stroke_width=0,
    ).move_to(CHAT_CENTER + np.array([0.05, -0.08, 0]))
    panel = RoundedRectangle(
        width=CHAT_W, height=CHAT_H, corner_radius=0.25,
        fill_color=CHAT_BG, fill_opacity=1.0,
        stroke_color=CHAT_BORDER, stroke_opacity=1.0, stroke_width=1.0,
    ).move_to(CHAT_CENTER)
    return shadow, panel


def _avatar(color, position):
    return Circle(
        radius=0.32, color=color, fill_color=color, fill_opacity=1.0,
        stroke_width=0,
    ).move_to(position)


def _user_bubble():
    """Grey bubble for user messages (matches chat.css .chat-bubble-user)."""
    return RoundedRectangle(
        width=USER_BUBBLE_W, height=USER_BUBBLE_H, corner_radius=0.18,
        fill_color=USER_BUBBLE_BG, fill_opacity=1.0, stroke_width=0,
    ).move_to(USER_BUBBLE_CTR)


def _ai_bubble():
    """White bubble with subtle border (matches chat.css .chat-bubble-assistant)."""
    return RoundedRectangle(
        width=AI_BUBBLE_W, height=AI_BUBBLE_H, corner_radius=0.18,
        fill_color=AI_BUBBLE_BG, fill_opacity=1.0,
        stroke_color=AI_BUBBLE_BORDER, stroke_opacity=1.0, stroke_width=1.0,
    ).move_to(AI_BUBBLE_CTR)


def _input_box():
    return RoundedRectangle(
        width=INPUT_W, height=INPUT_H, corner_radius=0.16,
        fill_color=INPUT_BG, fill_opacity=1.0,
        stroke_color=INPUT_BORDER, stroke_opacity=1.0, stroke_width=1.0,
    ).move_to(INPUT_CTR)


def _typing_dots(position):
    """Three small grey dots, used as the 'AI is thinking' indicator."""
    dots = VGroup()
    for i in range(3):
        dots.add(Dot(
            position + np.array([0.30 * i, 0, 0]),
            radius=0.07, color="#888888", fill_opacity=0.75,
        ))
    return dots


def _diary_card(date_str, snippet):
    """Small floating card: date + italic snippet. Looks like a single
    diary entry getting consulted."""
    card_rect = RoundedRectangle(
        width=3.0, height=0.85, corner_radius=0.12,
        fill_color="#ffffff", fill_opacity=0.95,
        stroke_color=AI_AVATAR_COLOR, stroke_opacity=0.55, stroke_width=1.0,
    )
    date = Text(date_str, font="Times New Roman", color=TEXT_MUTED, font_size=13)
    quote = Text(snippet, font="Times New Roman", slant=ITALIC,
                 color=TEXT_DARK, font_size=14)
    content = VGroup(date, quote).arrange(DOWN, buff=0.04)
    content.move_to(card_rect.get_center())
    return VGroup(card_rect, content)


# ── Main scene helper ─────────────────────────────────────────────

def _render_chat(scene, question, answer, highlights, diary_cards,
                 input_hint, privacy, title, subtitle):
    scene.camera.background_color = BG

    # ── BUILD: panel + skeleton (avatars/bubbles hidden initially) ──
    shadow, panel = _chat_container()
    input_box = _input_box()
    input_hint_text = Text(input_hint, font="Times New Roman", slant=ITALIC,
                           color=TEXT_MUTED, font_size=17)
    # Left-align inside the input box.
    input_hint_text.move_to(input_box.get_left() + RIGHT * 0.55)

    # A single text mobject — starts in the input, ends up inside the bubble.
    question_text = Text(question, font="Times New Roman",
                         color=TEXT_DARK, font_size=18)
    question_text.move_to(input_box.get_left() + RIGHT * (question_text.width / 2 + 0.55))

    user_avatar = _avatar(USER_AVATAR_COLOR, USER_AVATAR_POS)
    user_bubble = _user_bubble()
    ai_avatar = _avatar(AI_AVATAR_COLOR, AI_AVATAR_POS)
    ai_bubble = _ai_bubble()
    ai_text = Text(
        answer, font="Times New Roman", color=TEXT_DARK, font_size=15,
        line_spacing=0.5, t2c={h: HIGHLIGHT for h in highlights},
    )
    ai_text.move_to(ai_bubble.get_center())

    typing = _typing_dots(AI_AVATAR_POS + np.array([0.85, 0, 0]))

    # Cards positioned outside the chat — they drift in and converge.
    cards = []
    for (date_str, snippet), start in zip(diary_cards, CARD_START_POSITIONS):
        c = _diary_card(date_str, snippet)
        c.move_to(start)
        cards.append(c)

    # Outro
    privacy_text = Text(privacy, font="Times New Roman", slant=ITALIC,
                        color="#888888", font_size=18)
    title_text = Text(title, font="Times New Roman",
                      color="#ffffff", font_size=38)
    subtitle_text = Text(subtitle, font="Times New Roman", slant=ITALIC,
                         color="#a0a0a0", font_size=20)
    title_group = VGroup(title_text, subtitle_text).arrange(DOWN, buff=0.12)

    # ── ANIMATE ──────────────────────────────────────────────

    # 0 – 1 s : chat panel fades in (empty, just the input visible)
    scene.play(FadeIn(shadow), FadeIn(panel), run_time=0.55)
    scene.play(FadeIn(input_box), FadeIn(input_hint_text), run_time=0.4)
    scene.wait(0.15)

    # 1 – 3.5 s : the user types the question into the input box.
    scene.play(FadeOut(input_hint_text), run_time=0.15)
    scene.play(Write(question_text), run_time=1.8)
    scene.wait(0.3)

    # 3.5 – 4.4 s : "send" — text lifts into the user message bubble,
    # the bubble and avatar appear at the top of the chat.
    scene.play(
        question_text.animate.move_to(USER_BUBBLE_CTR),
        FadeIn(user_bubble),
        FadeIn(user_avatar),
        run_time=0.75,
    )
    scene.wait(0.25)

    # 4.4 – 5.0 s : AI's avatar and the typing indicator appear.
    scene.play(FadeIn(ai_avatar), FadeIn(typing), run_time=0.45)

    # 5.0 – 8.5 s : diary cards drift in around the chat, hold so the
    # viewer can read each excerpt, then converge on the typing dots
    # and fade as the AI "absorbs" them.
    for c in cards:
        scene.play(FadeIn(c, scale=0.9), run_time=0.35)
        scene.wait(0.28)
    scene.wait(0.3)

    target = AI_AVATAR_POS + np.array([0.85, 0, 0])
    scene.play(
        *[c.animate.move_to(target).scale(0.45).set_opacity(0) for c in cards],
        FadeOut(typing),
        run_time=0.85,
    )

    # 8.5 – 11.5 s : AI bubble appears and the answer types in.
    scene.play(FadeIn(ai_bubble), run_time=0.45)
    scene.play(Write(ai_text), run_time=2.4)
    scene.wait(0.5)

    # 11.5 – 12.5 s : input fades — conversation has happened.
    scene.play(FadeOut(input_box), run_time=0.4)

    # 12.5 – 14.5 s : compose down + outro text outside the chat
    chat_objects = VGroup(
        shadow, panel,
        user_avatar, user_bubble, question_text,
        ai_avatar, ai_bubble, ai_text,
    )
    scene.play(
        chat_objects.animate.scale(0.88).shift(UP * 0.45),
        run_time=0.7,
    )

    privacy_text.next_to(chat_objects, DOWN, buff=0.25)
    title_group.next_to(privacy_text, DOWN, buff=0.20)

    scene.play(FadeIn(privacy_text, shift=UP * 0.1), run_time=0.5)
    scene.play(FadeIn(title_group, shift=UP * 0.15), run_time=0.7)
    scene.wait(1.8)


# ── Scene classes ─────────────────────────────────────────────────

class AIPsychologistIntro(Scene):
    """Russian-language AI Psychologist intro.

    Render: manim -qh promo/ai_psychologist_intro.py AIPsychologistIntro
    """
    def construct(self):
        _render_chat(
            self, QUESTION_RU, ANSWER_RU, HIGHLIGHTS_RU, DIARY_CARDS_RU,
            INPUT_HINT_RU, PRIVACY_RU, TITLE_RU, SUBTITLE_RU,
        )


class AIPsychologistIntroEN(Scene):
    """English mirror.

    Render: manim -qh promo/ai_psychologist_intro.py AIPsychologistIntroEN
    """
    def construct(self):
        _render_chat(
            self, QUESTION_EN, ANSWER_EN, HIGHLIGHTS_EN, DIARY_CARDS_EN,
            INPUT_HINT_EN, PRIVACY_EN, TITLE_EN, SUBTITLE_EN,
        )
