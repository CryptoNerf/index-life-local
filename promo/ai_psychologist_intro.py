"""Promo motion graphics — AI Psychologist intro (~20 s, 1080p).

Black canvas; a wireframe sketch of the actual chat shell sits in the
middle (status line counting embedded/summarized entries + a profile
version, a toolbar row, the AI's pre-existing welcome bubble, the
input row with a Send button). The user types a question and sends
it. After Send, the chat ghosts and the three real powers the model
leans on each expand from the very header tag that names them:

    embedded     → a cloud of points fills the canvas; a beam from the
                   user's bubble lights up its nearest semantic
                   neighbours.
    summarized   → a stack of compact summary cards rises on the right
                   edge; the three that match glow.
    profile v3   → a wireframe silhouette assembles on the left edge,
                   surrounded by trait tags drawn from the diary.

All three highlighted matches then trace back into a single point in
the chat body, where the AI bubble materialises and the answer types
in — with the quoted fragments tinted amber so the viewer can see the
words came straight from the user's own entries.

Render:
    manim -qh promo/ai_psychologist_intro.py AIPsychologistIntro
    manim -qh promo/ai_psychologist_intro.py AIPsychologistIntroEN
"""
from manim import *
import numpy as np


# ── Palette ──────────────────────────────────────────────────────
# Everything reads against the black scene bg — no white panels.
BG          = "#0a0a0a"
LINE        = "#3a3a3a"    # base wireframe strokes
LINE_BRIGHT = "#8a8a8a"    # active stroke (input focus, active message)
TEXT_DIM    = "#7a7a7a"    # status counts, toolbar labels, placeholder
TEXT_BODY   = "#d4d4d4"    # bubble text, summary text
TEXT_BRIGHT = "#ffffff"    # the active question and final answer
TEXT_HEAD   = "#e6e6e6"    # title

AI_AVATAR_COLOR   = "#009AFA"   # brand cyan (matches in-app default)
USER_AVATAR_COLOR = "#FFA340"   # warm amber

HIGHLIGHT   = "#FFB347"    # quoted fragments in the answer (warm amber)
MATCH_GLOW  = "#FFD24A"    # mustard — lit-up matches across all three layers

SEND_BG     = "#1f1f1f"
SEND_TEXT   = "#dcdcdc"


# ── Layout ───────────────────────────────────────────────────────
# Manim default camera: ~-7.11..7.11 horizontal × -4..4 vertical.
# Chat panel sits centred, with room on the sides + above for the
# three-layer x-ray to expand into.
CHAT_W, CHAT_H = 8.0, 5.4
CHAT_CTR       = np.array([0, 0.05, 0])

CHAT_LEFT   = CHAT_CTR[0] - CHAT_W / 2
CHAT_RIGHT  = CHAT_CTR[0] + CHAT_W / 2
CHAT_TOP    = CHAT_CTR[1] + CHAT_H / 2
CHAT_BOTTOM = CHAT_CTR[1] - CHAT_H / 2

# Inner row y-coords (top → bottom)
ROW_STATUS_Y    = CHAT_TOP - 0.34
ROW_TOOLBAR_Y   = CHAT_TOP - 0.92
WELCOME_Y       = CHAT_TOP - 1.85
USER_MSG_Y      = CHAT_TOP - 2.95
AI_MSG_Y        = CHAT_TOP - 4.05
INPUT_Y         = CHAT_BOTTOM + 0.50


# ── Text packs ───────────────────────────────────────────────────
# The toolbar + status string are intentionally in English in both
# versions — that's how the real app shows them today.
TOOLBAR        = ["Compress", "Clear chat", "Sync", "Reindex", "Rebuild profile"]
STATUS_EMBED   = "238/238 embedded"
STATUS_SUMM    = "238/238 summarized"
STATUS_PROF    = "profile v3"
CONTEXT_LABEL  = "Context fill:"
CONTEXT_PCT    = "13%"

# Russian pack ────────────────────────────────────────────────────
WELCOME_RU = ("Привет. Я твой ИИ-психолог. У меня есть доступ к твоему\n"
              "дневнику настроения. Чем сегодня поделишься?")
QUESTION_RU = "Почему я в последнее время устаю?"
ANSWER_RU = (
    "За последние два месяца ты часто упоминал «опять никуда не\n"
    "успеваю» и «перерабатываю». Похоже, есть устойчивое чувство\n"
    "гонки против времени. Что важнее всего отпустить прямо сейчас?"
)
HIGHLIGHTS_RU = ["«опять никуда не\nуспеваю»", "«перерабатываю»"]
SUMMARIES_RU = [
    ("12 мар", "опять никуда не успеваю"),
    ("5 апр",  "снова перерабатываю"),
    ("21 апр", "гонка против времени"),
]
TRAITS_RU = ["переутомление", "гонка со временем", "трудно отпускать"]
PROFILE_TITLE_RU = "профиль"
INPUT_HINT_RU = "Сообщение…"
SEND_RU = "Отправить"
TITLE_RU    = "ИИ-психолог"
SUBTITLE_RU = "видит, что стоит за словами"

# English pack ────────────────────────────────────────────────────
WELCOME_EN = ("Hi. I'm your AI psychologist. I have access to your\n"
              "mood diary. What's on your mind today?")
QUESTION_EN = "Why have I been so tired lately?"
ANSWER_EN = (
    "Over the past two months you've often written «I never make it»\n"
    "and «I keep overworking». There's a persistent sense of racing\n"
    "against time. What feels most important to let go of right now?"
)
HIGHLIGHTS_EN = ["«I never make it»", "«I keep overworking»"]
SUMMARIES_EN = [
    ("Mar 12", "I never make it"),
    ("Apr 5",  "I keep overworking"),
    ("Apr 21", "racing against time"),
]
TRAITS_EN = ["overextension", "racing the clock", "letting go is hard"]
PROFILE_TITLE_EN = "profile"
INPUT_HINT_EN = "Write a message…"
SEND_EN = "Send"
TITLE_EN    = "AI Psychologist"
SUBTITLE_EN = "sees what's behind the words"


# ── Small builders ───────────────────────────────────────────────

def _panel():
    """The wireframe outline of the whole chat shell."""
    return RoundedRectangle(
        width=CHAT_W, height=CHAT_H, corner_radius=0.22,
        color=LINE, stroke_width=1.6, fill_opacity=0,
    ).move_to(CHAT_CTR)


def _divider(y, x_inset=0.25):
    """Thin horizontal rule across the chat."""
    return Line(
        np.array([CHAT_LEFT + x_inset, y, 0]),
        np.array([CHAT_RIGHT - x_inset, y, 0]),
        stroke_color=LINE, stroke_width=1.0,
    )


def _ui_text(s, size=14, color=TEXT_DIM):
    return Text(s, font="Helvetica", color=color, font_size=size)


def _body_text(s, size=17, color=TEXT_BODY, italic=False):
    kw = dict(font="Times New Roman", color=color, font_size=size, line_spacing=0.55)
    if italic:
        kw["slant"] = ITALIC
    return Text(s, **kw)


def _avatar_dot(color, position, radius=0.20):
    return Dot(position, radius=radius, color=color, fill_opacity=1.0)


def _wireframe_button(label, padding_x=0.18):
    text = _ui_text(label, size=13, color=TEXT_DIM)
    rect = RoundedRectangle(
        width=text.width + padding_x * 2, height=0.34, corner_radius=0.06,
        color=LINE, stroke_width=1.0, fill_opacity=0,
    )
    text.move_to(rect.get_center())
    return VGroup(rect, text)


def _wireframe_bubble(text_mob, pad_x=0.25, pad_y=0.18, min_w=2.0):
    w = max(text_mob.width + pad_x * 2, min_w)
    h = text_mob.height + pad_y * 2
    rect = RoundedRectangle(
        width=w, height=h, corner_radius=0.16,
        color=LINE, stroke_width=1.2, fill_opacity=0,
    )
    rect.move_to(text_mob.get_center())
    return rect


def _summary_card(date_str, snippet, width=2.6, highlighted=False):
    stroke_color = MATCH_GLOW if highlighted else LINE
    stroke_w = 1.5 if highlighted else 1.0
    text_color = TEXT_BRIGHT if highlighted else TEXT_DIM
    rect = RoundedRectangle(
        width=width, height=0.46, corner_radius=0.08,
        color=stroke_color, stroke_width=stroke_w, fill_opacity=0,
    )
    date = _ui_text(date_str, size=11, color=text_color)
    quote = _ui_text(snippet, size=12, color=text_color)
    row = VGroup(date, quote).arrange(RIGHT, buff=0.20, aligned_edge=DOWN)
    row.move_to(rect.get_center())
    return VGroup(rect, row)


def _placeholder_card(width=2.6):
    rect = RoundedRectangle(
        width=width, height=0.36, corner_radius=0.08,
        color=LINE, stroke_width=0.8, fill_opacity=0,
    )
    dots = _ui_text("· · · · · · · · · · · ·", size=10, color=LINE)
    dots.move_to(rect.get_center())
    return VGroup(rect, dots)


# ── Main scene helper ────────────────────────────────────────────

def _render_chat(scene, *, question, welcome, answer, highlights,
                 summaries, traits, profile_label, input_hint, send_label,
                 title, subtitle):
    scene.camera.background_color = BG
    rng = np.random.default_rng(11)

    # ─────────────── BUILD: chat shell ───────────────
    panel = _panel()

    # Status row — three separately positioned tags so we can pulse + spawn
    # the visualisation FROM each one.
    status_embed = _ui_text(STATUS_EMBED, size=14)
    status_dot1  = _ui_text("·", size=14)
    status_summ  = _ui_text(STATUS_SUMM, size=14)
    status_dot2  = _ui_text("·", size=14)
    status_prof  = _ui_text(STATUS_PROF, size=14)
    status_row = VGroup(status_embed, status_dot1, status_summ,
                        status_dot2, status_prof).arrange(RIGHT, buff=0.20)
    status_row.move_to([CHAT_LEFT + status_row.width / 2 + 0.35,
                        ROW_STATUS_Y, 0])

    ctx_label = _ui_text(CONTEXT_LABEL, size=12)
    ctx_pct   = _ui_text(CONTEXT_PCT,   size=12, color=TEXT_BODY)
    ctx_bar_outline = Rectangle(width=0.85, height=0.18, color=LINE,
                                stroke_width=1.0, fill_opacity=0)
    ctx_bar_fill = Rectangle(width=0.85 * 0.13, height=0.18,
                             color=LINE_BRIGHT, fill_opacity=0.7,
                             stroke_width=0)
    ctx_bar_fill.move_to(ctx_bar_outline.get_left()
                         + RIGHT * ctx_bar_fill.width / 2)
    ctx_bar = VGroup(ctx_bar_outline, ctx_bar_fill)
    ctx_group = VGroup(ctx_label, ctx_bar, ctx_pct).arrange(RIGHT, buff=0.14)
    ctx_group.move_to([CHAT_RIGHT - ctx_group.width / 2 - 0.35,
                       ROW_STATUS_Y, 0])

    status_divider = _divider(CHAT_TOP - 0.62)

    # Toolbar
    toolbar = VGroup(*[_wireframe_button(b) for b in TOOLBAR]).arrange(RIGHT, buff=0.14)
    toolbar.move_to([CHAT_CTR[0], ROW_TOOLBAR_Y, 0])

    toolbar_divider = _divider(CHAT_TOP - 1.20)

    # AI welcome bubble (pre-existing in the chat history)
    welcome_text = _body_text(welcome, size=16, color=TEXT_BODY)
    welcome_bubble_outline = _wireframe_bubble(welcome_text, pad_x=0.30, pad_y=0.20)
    welcome_avatar = _avatar_dot(AI_AVATAR_COLOR,
                                 np.array([CHAT_LEFT + 0.55, WELCOME_Y, 0]),
                                 radius=0.18)
    welcome_group = VGroup(welcome_bubble_outline, welcome_text)
    welcome_group.move_to([CHAT_LEFT + 0.95 + welcome_group.width / 2,
                           WELCOME_Y, 0])

    # Input row (initially placeholder + Send button)
    send_text = _ui_text(send_label, size=14, color=SEND_TEXT)
    send_btn  = RoundedRectangle(
        width=send_text.width + 0.55, height=0.50, corner_radius=0.09,
        color=LINE_BRIGHT, stroke_width=1.0,
        fill_color=SEND_BG, fill_opacity=1.0,
    )
    send_btn.move_to([CHAT_RIGHT - send_btn.width / 2 - 0.35,
                      INPUT_Y, 0])
    send_text.move_to(send_btn.get_center())
    send_group = VGroup(send_btn, send_text)

    input_left  = CHAT_LEFT + 0.35
    input_right = send_btn.get_left()[0] - 0.20
    input_w     = input_right - input_left
    input_box = RoundedRectangle(
        width=input_w, height=0.50, corner_radius=0.09,
        color=LINE, stroke_width=1.0, fill_opacity=0,
    )
    input_box.move_to([(input_left + input_right) / 2, INPUT_Y, 0])
    input_placeholder = _body_text(input_hint, size=15, italic=True,
                                   color=TEXT_DIM)
    input_placeholder.move_to(input_box.get_left() + RIGHT * 0.35
                              + RIGHT * input_placeholder.width / 2)

    input_divider = _divider(INPUT_Y + 0.45)

    # The question — starts in the input box, will travel into a user bubble.
    question_text = _body_text(question, size=17, color=TEXT_BRIGHT)
    question_text.move_to(input_box.get_left() + RIGHT * 0.35
                          + RIGHT * question_text.width / 2)

    chat_shell = VGroup(
        panel, status_row, ctx_group, status_divider,
        toolbar, toolbar_divider,
        welcome_avatar, welcome_group,
        input_divider, input_box, send_group,
    )

    # ─────────────── BUILD: user message slot (revealed on Send) ───
    user_avatar = _avatar_dot(USER_AVATAR_COLOR,
                              np.array([CHAT_RIGHT - 0.55, USER_MSG_Y, 0]),
                              radius=0.18)
    user_msg_text = _body_text(question, size=17, color=TEXT_BRIGHT)
    user_bubble = _wireframe_bubble(user_msg_text, pad_x=0.30, pad_y=0.20)
    user_msg_group = VGroup(user_bubble, user_msg_text)
    user_msg_group.move_to(
        [CHAT_RIGHT - 0.95 - user_msg_group.width / 2, USER_MSG_Y, 0]
    )
    # Reset opacity for the reveal
    user_msg_group.set_opacity(0)
    user_avatar.set_opacity(0)

    # ─────────────── BUILD: layer 1 — embedded cloud ───────────────
    # Pre-pick a deliberate cluster of 4 "matches" up-left of the chat,
    # then sprinkle ~80 background dots across the canvas around (and
    # behind) the chat. The chat strokes will read over the dots.
    match_positions = [
        np.array([-5.8,  2.2, 0]),
        np.array([-5.0,  2.7, 0]),
        np.array([-6.2,  1.5, 0]),
        np.array([-5.3,  1.6, 0]),
    ]
    match_dots = [Dot(p, radius=0.07, color=MATCH_GLOW,
                      fill_opacity=0) for p in match_positions]

    bg_dots = []
    for _ in range(82):
        x = rng.uniform(-6.9, 6.9)
        y = rng.uniform(-3.6, 3.6)
        # Skip the inside of the chat panel — would look noisy
        # under all the text.
        if (CHAT_LEFT - 0.1 < x < CHAT_RIGHT + 0.1 and
                CHAT_BOTTOM - 0.1 < y < CHAT_TOP + 0.1):
            continue
        d = Dot(np.array([x, y, 0]), radius=0.032,
                color=LINE_BRIGHT, fill_opacity=0)
        bg_dots.append(d)

    embed_cloud = VGroup(*bg_dots, *match_dots)
    # Lines from user bubble to each match (Q-vector)
    q_origin = np.array([user_msg_group.get_center()[0],
                         user_msg_group.get_center()[1], 0])

    # ─────────────── BUILD: layer 2 — summarized stack ─────────────
    # On the right margin (outside the chat). 6 cards total — 3 are
    # the real matches (highlighted), 3 are placeholders so the stack
    # feels like "many summaries scrolling".
    summary_x = 6.0
    summary_ys = [2.6, 1.95, 1.30, 0.65, 0.00, -0.65]
    summary_cards = []
    real_idxs = [0, 2, 4]   # alternating
    real_iter = iter(summaries)
    for i, y in enumerate(summary_ys):
        if i in real_idxs:
            date_s, snippet = next(real_iter)
            c = _summary_card(date_s, snippet, width=2.5, highlighted=True)
        else:
            c = _placeholder_card(width=2.5)
        c.move_to([summary_x, y, 0])
        c.set_opacity(0)
        summary_cards.append(c)

    # ─────────────── BUILD: layer 3 — profile silhouette ────────────
    # On the left margin (outside the chat). Stylised head + shoulders
    # outline, with trait tags orbiting it.
    profile_x = -5.9
    profile_ctr = np.array([profile_x, -1.5, 0])
    head = Circle(radius=0.32, color=LINE_BRIGHT, stroke_width=1.6,
                  fill_opacity=0).move_to(profile_ctr + UP * 0.55)
    # A trapezoid-ish "shoulders" silhouette.
    sh_y = profile_ctr[1] - 0.05
    shoulders = Polygon(
        np.array([profile_x - 0.72, sh_y - 0.35, 0]),
        np.array([profile_x + 0.72, sh_y - 0.35, 0]),
        np.array([profile_x + 0.42, sh_y + 0.25, 0]),
        np.array([profile_x - 0.42, sh_y + 0.25, 0]),
        color=LINE_BRIGHT, stroke_width=1.6, fill_opacity=0,
    )
    profile_label_text = _ui_text(profile_label, size=12,
                                  color=TEXT_DIM)
    profile_label_text.next_to(shoulders, DOWN, buff=0.20)
    profile_silhouette = VGroup(head, shoulders, profile_label_text)
    profile_silhouette.set_opacity(0)

    # Trait tags around the silhouette
    trait_anchors = [
        profile_ctr + UP * 2.20,                 # above the head
        profile_ctr + LEFT * 1.20 + DOWN * 0.65, # bottom-left
        profile_ctr + RIGHT * 1.30 + DOWN * 0.65,# bottom-right
    ]
    trait_groups = []
    for label, anchor in zip(traits, trait_anchors):
        t = _ui_text(label, size=12, color=MATCH_GLOW)
        rect = RoundedRectangle(
            width=t.width + 0.20, height=0.36, corner_radius=0.07,
            color=MATCH_GLOW, stroke_width=1.2, fill_opacity=0,
        )
        rect.move_to(t.get_center())
        g = VGroup(rect, t).move_to(anchor)
        g.set_opacity(0)
        trait_groups.append(g)

    # ─────────────── BUILD: AI answer (revealed at the end) ────────
    ai_avatar = _avatar_dot(AI_AVATAR_COLOR,
                            np.array([CHAT_LEFT + 0.55, AI_MSG_Y, 0]),
                            radius=0.18)
    # t2c tints the quoted fragments amber — the visual proof that the
    # quotes came straight from the diary the layers just showed.
    ai_text = Text(answer, font="Times New Roman", color=TEXT_BODY,
                   font_size=15, line_spacing=0.55,
                   t2c={h: HIGHLIGHT for h in highlights})
    ai_bubble = _wireframe_bubble(ai_text, pad_x=0.30, pad_y=0.22, min_w=5.5)
    ai_msg_group = VGroup(ai_bubble, ai_text)
    ai_msg_group.move_to(
        [CHAT_LEFT + 0.95 + ai_msg_group.width / 2, AI_MSG_Y, 0]
    )
    ai_msg_group.set_opacity(0)
    ai_avatar.set_opacity(0)

    # Outro
    title_text = Text(title, font="Times New Roman",
                      color=TEXT_HEAD, font_size=38)
    subtitle_text = Text(subtitle, font="Times New Roman", slant=ITALIC,
                         color="#9a9a9a", font_size=20)
    title_group = VGroup(title_text, subtitle_text).arrange(DOWN, buff=0.14)

    # ═══════════════ ANIMATE ═══════════════════════════════════════

    # ── ACT 1 ─ chat shell appears (wireframe assembles top-to-bottom)
    scene.play(Create(panel), run_time=0.7)
    scene.play(
        FadeIn(status_row, shift=DOWN * 0.1),
        FadeIn(ctx_group, shift=DOWN * 0.1),
        run_time=0.45,
    )
    scene.play(
        Create(status_divider),
        LaggedStart(*[FadeIn(b, shift=DOWN * 0.05) for b in toolbar],
                    lag_ratio=0.05),
        Create(toolbar_divider),
        run_time=0.7,
    )
    scene.play(
        FadeIn(welcome_avatar, shift=RIGHT * 0.1),
        FadeIn(welcome_group, shift=RIGHT * 0.15),
        run_time=0.7,
    )
    scene.play(
        Create(input_divider),
        FadeIn(input_box),
        FadeIn(send_group),
        FadeIn(input_placeholder),
        run_time=0.45,
    )
    scene.wait(0.3)

    # ── ACT 2 ─ user types the question into the input box
    scene.play(FadeOut(input_placeholder), run_time=0.15)
    scene.play(Write(question_text), run_time=1.6)
    scene.wait(0.25)

    # ── ACT 3 ─ Send pressed: text lifts into a user bubble, avatar fades in
    scene.play(Indicate(send_group, color=AI_AVATAR_COLOR,
                         scale_factor=1.05), run_time=0.35)
    target_in_bubble = user_msg_text.get_center()
    scene.play(
        question_text.animate.move_to(target_in_bubble),
        FadeIn(user_bubble),
        FadeIn(user_avatar),
        run_time=0.7,
    )
    # Hand the on-screen text over to the bubble's own text object.
    scene.remove(question_text)
    user_msg_text.set_opacity(1)
    scene.add(user_msg_text)
    scene.wait(0.35)

    # ── ACT 4 ─ chat ghosts; the three header tags about to spawn layers
    # stay bright while everything else dims.
    bright_tags = VGroup(status_embed, status_summ, status_prof)
    dim_targets = VGroup(
        panel, status_dot1, status_dot2, ctx_group, status_divider,
        toolbar, toolbar_divider,
        welcome_avatar, welcome_group,
        input_divider, input_box, send_group,
        user_avatar, user_msg_group,
    )
    scene.play(
        dim_targets.animate.set_opacity(0.18),
        bright_tags.animate.set_color(LINE_BRIGHT),
        run_time=0.55,
    )

    # Add the (still invisible) cloud behind the chat.
    scene.add(embed_cloud)
    embed_cloud.set_z_index(-1)
    panel.set_z_index(2)
    bright_tags.set_z_index(3)

    # ── ACT 5a ─ LAYER 1: embedded cloud expands from "238/238 embedded"
    scene.play(Indicate(status_embed, color=MATCH_GLOW,
                         scale_factor=1.10), run_time=0.4)
    scene.play(
        LaggedStart(*[d.animate.set_fill(opacity=0.55) for d in bg_dots],
                    lag_ratio=0.015),
        run_time=1.1,
    )
    # Q-beam from the user bubble to each match dot, then matches glow.
    q_lines = [
        Line(q_origin, p, stroke_color=MATCH_GLOW, stroke_width=1.5,
             stroke_opacity=0)
        for p in match_positions
    ]
    for ln in q_lines:
        scene.add(ln)
    scene.play(
        *[ln.animate.set_stroke(opacity=0.55) for ln in q_lines],
        *[d.animate.set_fill(opacity=1.0) for d in match_dots],
        run_time=0.8,
    )
    scene.wait(0.35)

    # ── ACT 5b ─ LAYER 2: summarized stack rises from "238/238 summarized"
    scene.play(Indicate(status_summ, color=MATCH_GLOW,
                         scale_factor=1.10), run_time=0.4)
    # Cards slide up in sequence with a small lag — feels like
    # scrolling through summaries.
    for c in summary_cards:
        c.shift(DOWN * 0.4)   # start a bit below their final position
    scene.play(
        LaggedStart(
            *[c.animate.shift(UP * 0.4).set_opacity(1) for c in summary_cards],
            lag_ratio=0.08,
        ),
        run_time=1.2,
    )
    scene.wait(0.4)

    # ── ACT 5c ─ LAYER 3: profile silhouette emerges from "profile v3"
    scene.play(Indicate(status_prof, color=MATCH_GLOW,
                         scale_factor=1.10), run_time=0.4)
    scene.play(
        Create(head), Create(shoulders),
        FadeIn(profile_label_text, shift=UP * 0.1),
        run_time=0.7,
    )
    profile_silhouette.set_opacity(1)
    scene.play(
        LaggedStart(*[FadeIn(g, scale=0.85) for g in trait_groups],
                    lag_ratio=0.18),
        run_time=1.0,
    )
    for g in trait_groups:
        g.set_opacity(1)
    scene.wait(0.5)

    # ── ACT 6 ─ all three layers compose into the AI's spot.
    # Highlighted matches collapse toward the AI avatar position.
    collapse_target = ai_avatar.get_center()
    layer_movers = [
        *[d.animate.move_to(collapse_target).scale(0.4).set_opacity(0)
          for d in match_dots],
        *[ln.animate.put_start_and_end_on(q_origin, collapse_target)
                    .set_stroke(opacity=0)
          for ln in q_lines],
        *[c.animate.move_to(collapse_target).scale(0.3).set_opacity(0)
          for i, c in enumerate(summary_cards) if i in real_idxs],
        *[c.animate.set_opacity(0) for i, c in enumerate(summary_cards) if i not in real_idxs],
        *[g.animate.move_to(collapse_target).scale(0.4).set_opacity(0)
          for g in trait_groups],
        profile_silhouette.animate.set_opacity(0),
        embed_cloud.animate.set_opacity(0),
    ]
    scene.play(*layer_movers, run_time=1.1)

    # Chat brightens back up.
    scene.play(
        dim_targets.animate.set_opacity(1.0),
        bright_tags.animate.set_color(TEXT_DIM),
        run_time=0.5,
    )

    # ── ACT 7 ─ AI bubble materialises at the AI's spot; answer types in.
    ai_avatar.set_opacity(1)
    ai_bubble.set_stroke(opacity=1)
    ai_msg_group.set_opacity(1)
    ai_text.set_opacity(0)
    scene.play(FadeIn(ai_avatar), FadeIn(ai_bubble), run_time=0.5)
    scene.play(Write(ai_text), run_time=2.6)
    scene.wait(0.6)

    # ── OUTRO ─ chat shifts up + scales; title fades in below.
    full_chat = VGroup(
        chat_shell, user_avatar, user_msg_group, ai_avatar, ai_msg_group,
    )
    title_group.next_to(full_chat, DOWN, buff=0.15)
    scene.play(
        full_chat.animate.scale(0.86).shift(UP * 0.40),
        run_time=0.7,
    )
    title_group.next_to(full_chat, DOWN, buff=0.25)
    scene.play(FadeIn(title_group, shift=UP * 0.15), run_time=0.7)
    scene.wait(1.8)


# ── Scene classes ─────────────────────────────────────────────────

class AIPsychologistIntro(Scene):
    """Russian-language AI Psychologist intro.

    Render: manim -qh promo/ai_psychologist_intro.py AIPsychologistIntro
    """
    def construct(self):
        _render_chat(
            self,
            question=QUESTION_RU,
            welcome=WELCOME_RU,
            answer=ANSWER_RU,
            highlights=HIGHLIGHTS_RU,
            summaries=SUMMARIES_RU,
            traits=TRAITS_RU,
            profile_label=PROFILE_TITLE_RU,
            input_hint=INPUT_HINT_RU,
            send_label=SEND_RU,
            title=TITLE_RU,
            subtitle=SUBTITLE_RU,
        )


class AIPsychologistIntroEN(Scene):
    """English mirror.

    Render: manim -qh promo/ai_psychologist_intro.py AIPsychologistIntroEN
    """
    def construct(self):
        _render_chat(
            self,
            question=QUESTION_EN,
            welcome=WELCOME_EN,
            answer=ANSWER_EN,
            highlights=HIGHLIGHTS_EN,
            summaries=SUMMARIES_EN,
            traits=TRAITS_EN,
            profile_label=PROFILE_TITLE_EN,
            input_hint=INPUT_HINT_EN,
            send_label=SEND_EN,
            title=TITLE_EN,
            subtitle=SUBTITLE_EN,
        )
