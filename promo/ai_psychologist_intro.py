"""Promo motion graphics — AI Psychologist intro (~24 s, 1080p).

Black canvas; wireframe sketch of the actual chat shell. The user types
a question and sends it. The AI replies with a "thinking" status message
and then, INSIDE THE CHAT, walks through the four real stages the model
goes through to answer:

    1. semantic search   — a pseudo-3D scatter of embedded diary
                            entries; the question lands as a vector,
                            cosine-similarity beams light up the 4
                            nearest neighbours.
    2. summary extraction — a compact list of the matching summaries
                            with their dates and similarity scores.
    3. psychological profile — the user's stored profile rendered as
                            real-looking JSON (the actual schema), with
                            traits / patterns / themes visible.
    4. answer composition — fragments retrieved from the previous steps
                            flow into the AI bubble that types the
                            final answer in, with the quoted fragments
                            tinted amber.

Each step's viz takes the chat-body area while it's active; the
previous steps stay above as a checked-off list ("✓ Step 1: …"), so
the viewer can follow the pipeline as it runs. After step 4 the
checklist collapses and the AI's final answer appears in its own
wireframe bubble.

A backup of the earlier "three-layer x-ray around the chat" take is
preserved in ai_psychologist_intro_xray.py.

Render:
    manim -qh promo/ai_psychologist_intro.py AIPsychologistIntro
    manim -qh promo/ai_psychologist_intro.py AIPsychologistIntroEN
"""
from manim import *
import numpy as np


# ── Palette ──────────────────────────────────────────────────────
BG          = "#0a0a0a"
LINE        = "#3a3a3a"    # base wireframe strokes
LINE_BRIGHT = "#8a8a8a"    # accented stroke (active step, send btn)
TEXT_DIM    = "#7a7a7a"    # status counts, toolbar labels, placeholders
TEXT_BODY   = "#d4d4d4"    # bubble text, list text
TEXT_BRIGHT = "#ffffff"    # user's typed message, final answer
TEXT_HEAD   = "#e6e6e6"    # title

AI_AVATAR_COLOR   = "#009AFA"   # brand cyan
USER_AVATAR_COLOR = "#FFA340"   # warm amber

HIGHLIGHT   = "#FFB347"    # quoted fragments in the answer
MATCH_GLOW  = "#FFD24A"    # mustard — matched embeddings, summary glow

# JSON code-block syntax colours (high contrast on black, but muted)
JSON_KEY    = "#7AB6FF"    # keys (light blue)
JSON_STR    = "#A5D6A7"    # string values (light green)
JSON_NUM    = "#FFCC66"    # numbers (amber)
JSON_PUNCT  = "#888888"    # braces, brackets, commas

SEND_BG     = "#1f1f1f"
SEND_TEXT   = "#dcdcdc"


# ── Layout ───────────────────────────────────────────────────────
# Manim default camera: ~-7.11..7.11 horizontal × -4..4 vertical.
CHAT_W, CHAT_H = 10.4, 6.6
CHAT_CTR       = np.array([0, 0.10, 0])

CHAT_LEFT   = CHAT_CTR[0] - CHAT_W / 2
CHAT_RIGHT  = CHAT_CTR[0] + CHAT_W / 2
CHAT_TOP    = CHAT_CTR[1] + CHAT_H / 2
CHAT_BOTTOM = CHAT_CTR[1] - CHAT_H / 2

# Inner rows (top → bottom, y-coords)
ROW_STATUS_Y    = CHAT_TOP - 0.32
ROW_TOOLBAR_Y   = CHAT_TOP - 0.92
USER_MSG_Y      = CHAT_TOP - 1.70
THINK_HEAD_Y    = CHAT_TOP - 2.55
# The active-step viz occupies the band from ~ y=-0.30 down to y=-2.05
VIZ_TOP_Y       = CHAT_TOP - 3.20
VIZ_BOTTOM_Y    = CHAT_BOTTOM + 1.10
VIZ_CTR_Y       = (VIZ_TOP_Y + VIZ_BOTTOM_Y) / 2
VIZ_W           = CHAT_W - 1.80   # 1.8 of side padding
INPUT_Y         = CHAT_BOTTOM + 0.42


# ── Text packs ───────────────────────────────────────────────────
TOOLBAR        = ["Compress", "Clear chat", "Sync", "Reindex", "Rebuild profile"]
STATUS_EMBED   = "238/238 embedded"
STATUS_SUMM    = "238/238 summarized"
STATUS_PROF    = "profile v3"
CONTEXT_LABEL  = "Context fill:"
CONTEXT_PCT    = "13%"

# Russian pack ────────────────────────────────────────────────────
QUESTION_RU = "Почему я в последнее время устаю?"
ANSWER_RU = (
    "За последние два месяца ты часто упоминал «опять никуда не\n"
    "успеваю» и «перерабатываю». А вот про отдых в записях почти\n"
    "ничего. Когда ты в последний раз давал себе день без задач?"
)
HIGHLIGHTS_RU = ["«опять никуда не\nуспеваю»", "«перерабатываю»"]
THINK_LABEL_RU = "думаю над ответом"
STEP_LABELS_RU = [
    "Поиск похожих записей",
    "Извлечение саммари",
    "Загрузка психопрофиля",
    "Формирование ответа",
]
SUMMARIES_RU = [
    ("12 мар", "опять никуда не успеваю", 0.87),
    ("5 апр",  "снова перерабатываю",      0.82),
    ("21 апр", "опять не выспался",        0.79),
]
# Sample of what app/modules/deep_mind actually stores per user: the
# psychological profile that informs every reply. Keys are illustrative
# but mirror the real schema (traits, patterns, themes…).
PROFILE_JSON_RU = [
    ('{',                   [('{', JSON_PUNCT)]),
    ('  "v"',               [('"v"', JSON_KEY), (': 3,', JSON_PUNCT)]),
    ('  "traits"',          [('"traits"', JSON_KEY), (': {', JSON_PUNCT)]),
    ('    "трудоголизм"',   [('"трудоголизм"', JSON_STR),
                             (': ',  JSON_PUNCT), ('0.81', JSON_NUM),
                             (',', JSON_PUNCT)]),
    ('    "перфекционизм"', [('"перфекционизм"', JSON_STR),
                             (': ', JSON_PUNCT), ('0.74', JSON_NUM)]),
    ('  },',                [('  },', JSON_PUNCT)]),
    ('  "pattern"',         [('"pattern"', JSON_KEY), (': ', JSON_PUNCT),
                             ('"хроническая перегрузка"', JSON_STR)]),
    ('}',                   [('}', JSON_PUNCT)]),
]
COMPOSE_FRAGMENTS_RU = [
    "«опять никуда не успеваю»",
    "«перерабатываю»",
    "«опять не выспался»",
]
INPUT_HINT_RU = "Сообщение…"
SEND_RU = "Отправить"
TITLE_RU    = "ИИ-психолог"
SUBTITLE_RU = "опирается на твой дневник"

# English pack ────────────────────────────────────────────────────
QUESTION_EN = "Why have I been so tired lately?"
ANSWER_EN = (
    "Over the past two months you've often written «I never make it»\n"
    "and «I keep overworking». But you barely mention rest at all.\n"
    "When did you last give yourself a day with no tasks?"
)
HIGHLIGHTS_EN = ["«I never make it»", "«I keep overworking»"]
THINK_LABEL_EN = "thinking"
STEP_LABELS_EN = [
    "Search similar entries",
    "Extract summaries",
    "Load psychological profile",
    "Compose the answer",
]
SUMMARIES_EN = [
    ("Mar 12", "I never make it",     0.87),
    ("Apr 5",  "I keep overworking",  0.82),
    ("Apr 21", "didn't sleep enough", 0.79),
]
PROFILE_JSON_EN = [
    ('{',                   [('{', JSON_PUNCT)]),
    ('  "v"',               [('"v"', JSON_KEY), (': 3,', JSON_PUNCT)]),
    ('  "traits"',          [('"traits"', JSON_KEY), (': {', JSON_PUNCT)]),
    ('    "workaholism"',   [('"workaholism"', JSON_STR),
                             (': ',  JSON_PUNCT), ('0.81', JSON_NUM),
                             (',', JSON_PUNCT)]),
    ('    "perfectionism"', [('"perfectionism"', JSON_STR),
                             (': ', JSON_PUNCT), ('0.74', JSON_NUM)]),
    ('  },',                [('  },', JSON_PUNCT)]),
    ('  "pattern"',         [('"pattern"', JSON_KEY), (': ', JSON_PUNCT),
                             ('"chronic overload"', JSON_STR)]),
    ('}',                   [('}', JSON_PUNCT)]),
]
COMPOSE_FRAGMENTS_EN = [
    "«I never make it»",
    "«I keep overworking»",
    "«didn't sleep enough»",
]
INPUT_HINT_EN = "Write a message…"
SEND_EN = "Send"
TITLE_EN    = "AI Psychologist"
SUBTITLE_EN = "grounded in your diary"


# ── Small builders ───────────────────────────────────────────────

def _panel():
    return RoundedRectangle(
        width=CHAT_W, height=CHAT_H, corner_radius=0.22,
        color=LINE, stroke_width=1.6, fill_opacity=0,
    ).move_to(CHAT_CTR)


def _divider(y, x_inset=0.30):
    return Line(
        np.array([CHAT_LEFT + x_inset, y, 0]),
        np.array([CHAT_RIGHT - x_inset, y, 0]),
        stroke_color=LINE, stroke_width=1.0,
    )


# Pango / Cairo quantise text metrics at small font_size values, which
# is why manim Text/MarkupText renders Cyrillic + small Latin with
# visible inter-letter gaps. Workaround (well-known in the manim
# community): render the mobject at a larger internal font size so
# Pango uses high-precision metrics, then scale the resulting SVG
# down. 36 is enough to fix the kerning without changing how Pango
# wraps multi-line text inside spans.
HIGH_DPI_SIZE = 36


def _high_dpi(mob_cls, s, size, **kwargs):
    target = mob_cls(s, font_size=HIGH_DPI_SIZE, **kwargs)
    target.scale(size / HIGH_DPI_SIZE)
    return target


def _ui_text(s, size=14, color=TEXT_DIM, font="Helvetica"):
    return _high_dpi(Text, s, size, font=font, color=color)


def _mono(s, size=14, color=TEXT_BODY):
    """Monospace text — used for JSON, lists, similarity numbers."""
    return _high_dpi(Text, s, size, font="Menlo", color=color)


def _body_text(s, size=17, color=TEXT_BODY, italic=False):
    kw = dict(font="DejaVu Serif", color=color, line_spacing=0.55)
    if italic:
        kw["slant"] = ITALIC
    return _high_dpi(MarkupText, s, size, **kw)


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


# ── Step header builder (the checklist line at the top of the body) ─

def _step_header(idx, label, state="pending"):
    """One row of the thinking checklist.

    state: 'pending' | 'active' | 'done'
    Layout: [⟳/✓/·] [Step N: <label>]
    """
    marker_text = {"pending": "·", "active": "⟳", "done": "✓"}[state]
    marker_color = {"pending": LINE, "active": MATCH_GLOW, "done": "#7DC36A"}[state]
    label_color  = {"pending": LINE, "active": TEXT_BODY, "done": TEXT_DIM}[state]
    marker = _ui_text(marker_text, size=14, color=marker_color, font="Helvetica")
    text = _ui_text(f"Шаг {idx}: {label}" if state != "header"
                    else label,
                    size=14, color=label_color)
    row = VGroup(marker, text).arrange(RIGHT, buff=0.16)
    return row


# ── Step 1: pseudo-3D embedding scatter ───────────────────────────

def _build_embedding_viz(rng, viz_center, viz_w, viz_h):
    """Pseudo-3D scatter — ~70 dots in a unit cube projected onto the
    plane. Size + opacity vary with depth (z). Returns:
      (group, query_dot, match_dots, q_lines, sim_labels)
    """
    n = 70
    cube_pts = []
    for _ in range(n):
        cube_pts.append((
            rng.uniform(-1, 1),
            rng.uniform(-1, 1),
            rng.uniform(-1, 1),
        ))

    def project(p):
        x, y, z = p
        # Slight tilt for perspective: shift x by z*0.08, scale y by 1.
        px = viz_center[0] + x * viz_w * 0.45 + z * 0.20
        py = viz_center[1] + y * viz_h * 0.42 + z * 0.10
        return np.array([px, py, 0])

    def depth_size(z):
        return 0.025 + 0.030 * ((z + 1) / 2)

    def depth_opacity(z):
        return 0.30 + 0.55 * ((z + 1) / 2)

    bg_dots = []
    for p in cube_pts:
        d = Dot(project(p), radius=depth_size(p[2]),
                color=LINE_BRIGHT, fill_opacity=depth_opacity(p[2]))
        bg_dots.append(d)

    # Hand-pick 4 "match" coordinates in the front-ish region (z > 0.2)
    match_pts_3d = [
        ( 0.55,  0.35, 0.55),
        (-0.30,  0.50, 0.40),
        ( 0.10, -0.25, 0.65),
        (-0.45, -0.10, 0.30),
    ]
    match_dots = []
    for p in match_pts_3d:
        d = Dot(project(p), radius=0.065, color=MATCH_GLOW, fill_opacity=0)
        match_dots.append(d)

    # Query "vector" — flies in from the left edge of the viz box,
    # parks at the centre of the cube.
    query_dot = Dot(
        np.array([viz_center[0] - viz_w/2 + 0.1, viz_center[1], 0]),
        radius=0.10, color=USER_AVATAR_COLOR, fill_opacity=0,
    )
    query_target = project((0, 0, 0))

    # Lines from query to each match.
    q_lines = [
        Line(query_target, m.get_center(),
             stroke_color=MATCH_GLOW, stroke_width=1.2, stroke_opacity=0)
        for m in match_dots
    ]

    # Similarity numbers (cosine sim) near each match dot.
    sims = [0.87, 0.82, 0.79, 0.71]
    sim_labels = []
    for m, s in zip(match_dots, sims):
        t = _mono(f"{s:.2f}", size=11, color=MATCH_GLOW)
        t.set_opacity(0)
        t.move_to(m.get_center() + np.array([0.32, 0.18, 0]))
        sim_labels.append(t)

    # Axis hint — three tiny tick marks suggesting (x, y, z) without
    # being too literal. Just a corner gnomon.
    gx = viz_center + np.array([-viz_w/2 + 0.20, -viz_h/2 + 0.20, 0])
    gnomon = VGroup(
        Line(gx, gx + np.array([0.35, 0, 0]),
             stroke_color=LINE, stroke_width=1.2),
        Line(gx, gx + np.array([0, 0.35, 0]),
             stroke_color=LINE, stroke_width=1.2),
        Line(gx, gx + np.array([0.20, 0.10, 0]),  # z fake-axis
             stroke_color=LINE, stroke_width=1.2),
    )
    axis_labels = VGroup(
        _mono("x", size=10, color=LINE).move_to(gx + np.array([0.42, -0.08, 0])),
        _mono("y", size=10, color=LINE).move_to(gx + np.array([-0.08, 0.42, 0])),
        _mono("z", size=10, color=LINE).move_to(gx + np.array([0.28, 0.18, 0])),
    )

    container = VGroup(
        *bg_dots, *match_dots, *q_lines, *sim_labels,
        gnomon, axis_labels, query_dot,
    )
    return container, query_dot, match_dots, q_lines, sim_labels, bg_dots, query_target


# ── Step 2: summary list ──────────────────────────────────────────

def _build_summary_viz(summaries, viz_center, viz_w, viz_h):
    """A monospace-styled list:

        [
          {date: "12 мар", text: "…", sim: 0.87},
          ...
        ]
    """
    lines = []
    lines.append(_mono("[", size=12, color=JSON_PUNCT))
    for i, (date_s, text_s, sim) in enumerate(summaries):
        comma = "," if i < len(summaries) - 1 else ""
        # Build per-segment so we can colour key/value pairs.
        parts = [
            ("  { ", JSON_PUNCT),
            ('date', JSON_KEY), (': ', JSON_PUNCT),
            (f'"{date_s}"', JSON_STR), (', ', JSON_PUNCT),
            ('text', JSON_KEY), (': ', JSON_PUNCT),
            (f'"{text_s}"', JSON_STR), (', ', JSON_PUNCT),
            ('sim', JSON_KEY), (': ', JSON_PUNCT),
            (f'{sim:.2f}', JSON_NUM),
            (' }' + comma, JSON_PUNCT),
        ]
        row = VGroup()
        for s, c in parts:
            row.add(_mono(s, size=11, color=c))
        row.arrange(RIGHT, buff=0.03, aligned_edge=DOWN)
        lines.append(row)
    lines.append(_mono("]", size=12, color=JSON_PUNCT))

    block = VGroup(*lines).arrange(DOWN, buff=0.08, aligned_edge=LEFT)
    _fit_inside(block, viz_w, viz_h)
    block.move_to(viz_center)
    return block


def _fit_inside(block, w, h, margin=0.40):
    """Scale `block` down (never up) so it fits inside (w-margin, h-margin)."""
    target_w = w - margin
    target_h = h - margin
    factor = min(1.0, target_w / max(block.width, 0.01),
                      target_h / max(block.height, 0.01))
    if factor < 1.0:
        block.scale(factor)


# ── Step 3: JSON profile ──────────────────────────────────────────

def _build_profile_viz(profile_spec, viz_center, viz_w, viz_h):
    """Render the profile JSON line-by-line with syntax colouring.

    profile_spec: list of (plain_line, [(segment, colour), …]).
    If the segments list is empty the plain_line is shown as JSON_PUNCT.
    """
    lines = []
    JSON_FONT = 12
    for plain, segments in profile_spec:
        if not segments:
            lines.append(_mono(plain, size=JSON_FONT, color=JSON_PUNCT))
            continue
        # Indent is preserved by prefixing the row with leading spaces
        # rendered as a JSON_PUNCT-coloured mono blob.
        indent = len(plain) - len(plain.lstrip(' '))
        row = VGroup()
        if indent > 0:
            row.add(_mono(' ' * indent, size=JSON_FONT, color=JSON_PUNCT))
        for s, c in segments:
            row.add(_mono(s, size=JSON_FONT, color=c))
        row.arrange(RIGHT, buff=0.02, aligned_edge=DOWN)
        lines.append(row)

    block = VGroup(*lines).arrange(DOWN, buff=0.06, aligned_edge=LEFT)
    _fit_inside(block, viz_w, viz_h)
    block.move_to(viz_center)
    return block


# ── Step 4: composition viz ───────────────────────────────────────

def _build_compose_viz(fragments, viz_center, viz_w, viz_h):
    """Three quote-fragments interspersed with a '+' between each, to
    say "all of these feed into the final answer." Returns the full
    VGroup (fragments + pluses, alternating) plus the index list of
    just-the-fragment children so the scene can animate them in
    different beats."""
    items = []
    fragment_idx = []   # indices of fragment mobjects inside `items`
    plus_idx     = []   # indices of "+" mobjects inside `items`
    for i, f in enumerate(fragments):
        t = _high_dpi(MarkupText, f, 15, font="DejaVu Serif",
                      slant=ITALIC, color=HIGHLIGHT)
        fragment_idx.append(len(items))
        items.append(t)
        if i < len(fragments) - 1:
            plus = _high_dpi(MarkupText, "+", 20, font="DejaVu Serif",
                             color=TEXT_DIM, weight=BOLD)
            plus_idx.append(len(items))
            items.append(plus)
    group = VGroup(*items).arrange(DOWN, buff=0.20)
    _fit_inside(group, viz_w, viz_h)
    group.move_to(viz_center)
    return group, fragment_idx, plus_idx


# ── Main scene helper ────────────────────────────────────────────

def _render_chat(scene, *, question, answer, highlights, summaries,
                 profile_spec, fragments, think_label, step_labels,
                 input_hint, send_label, title, subtitle):
    scene.camera.background_color = BG
    rng = np.random.default_rng(23)

    # ─────────────── BUILD: chat shell ───────────────
    panel = _panel()

    # Status row
    status_embed = _ui_text(STATUS_EMBED, size=14)
    status_dot1  = _ui_text("·", size=14)
    status_summ  = _ui_text(STATUS_SUMM, size=14)
    status_dot2  = _ui_text("·", size=14)
    status_prof  = _ui_text(STATUS_PROF, size=14)
    status_row = VGroup(status_embed, status_dot1, status_summ,
                        status_dot2, status_prof).arrange(RIGHT, buff=0.20)
    status_row.move_to([CHAT_LEFT + status_row.width / 2 + 0.40,
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
    ctx_group.move_to([CHAT_RIGHT - ctx_group.width / 2 - 0.40,
                       ROW_STATUS_Y, 0])

    status_divider = _divider(CHAT_TOP - 0.60)

    # Toolbar
    toolbar = VGroup(*[_wireframe_button(b) for b in TOOLBAR]).arrange(RIGHT, buff=0.14)
    toolbar.move_to([CHAT_CTR[0], ROW_TOOLBAR_Y, 0])
    toolbar_divider = _divider(CHAT_TOP - 1.20)

    # Input row
    send_text = _ui_text(send_label, size=14, color=SEND_TEXT)
    send_btn  = RoundedRectangle(
        width=send_text.width + 0.55, height=0.50, corner_radius=0.09,
        color=LINE_BRIGHT, stroke_width=1.0,
        fill_color=SEND_BG, fill_opacity=1.0,
    )
    send_btn.move_to([CHAT_RIGHT - send_btn.width / 2 - 0.40,
                      INPUT_Y, 0])
    send_text.move_to(send_btn.get_center())
    send_group = VGroup(send_btn, send_text)

    input_left  = CHAT_LEFT + 0.40
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

    # The question text — starts in the input, will move to user bubble.
    question_text = _body_text(question, size=15, color=TEXT_BRIGHT)
    question_text.move_to(input_box.get_left() + RIGHT * 0.35
                          + RIGHT * question_text.width / 2)

    # User message bubble (right-aligned)
    user_avatar = _avatar_dot(USER_AVATAR_COLOR,
                              np.array([CHAT_RIGHT - 0.55, USER_MSG_Y, 0]),
                              radius=0.18)
    user_msg_text = _body_text(question, size=15, color=TEXT_BRIGHT)
    user_bubble = _wireframe_bubble(user_msg_text, pad_x=0.30, pad_y=0.20)
    user_msg_group = VGroup(user_bubble, user_msg_text)
    user_msg_group.move_to(
        [CHAT_RIGHT - 0.95 - user_msg_group.width / 2, USER_MSG_Y, 0]
    )

    chat_shell = VGroup(
        panel, status_row, ctx_group, status_divider,
        toolbar, toolbar_divider,
        input_divider, input_box, send_group,
    )

    # ─────────────── BUILD: thinking area (the in-chat pipeline) ───
    ai_think_avatar = _avatar_dot(AI_AVATAR_COLOR,
                                  np.array([CHAT_LEFT + 0.55, THINK_HEAD_Y, 0]),
                                  radius=0.18)
    think_marker = _ui_text("⟳", size=15, color=MATCH_GLOW, font="Helvetica")
    think_label_text = _ui_text(think_label + "…", size=15, color=TEXT_BODY)
    think_header = VGroup(think_marker, think_label_text).arrange(RIGHT, buff=0.16)
    think_header.move_to([CHAT_LEFT + 0.95 + think_header.width / 2,
                          THINK_HEAD_Y, 0])

    # Build the four checklist rows. We use Dot markers (geometry, not
    # text) for the state indicator so we can morph their colour/size
    # cleanly without Transform-ing Cyrillic Text glyphs (which loses
    # the spacing between words in Pango). Labels stay as static Text
    # mobjects whose colour we animate.
    step_dots = []
    step_labels_mobs = []
    step_checks = []  # tiny green tick added when step completes
    step_rows = []
    for label in step_labels:
        marker = Dot(radius=0.06, color=LINE, fill_opacity=0.35)
        # No "Шаг N." prefix — the label is shorter and reads cleaner;
        # the step's place in the pipeline is conveyed by its vertical
        # position in the checklist + the active-marker state.
        label_text = _ui_text(label, size=14, color=LINE)
        # Pre-built check mark — full opacity but not yet in scene;
        # FadeIn() in _complete_step adds and reveals it.
        check = VGroup(
            Line(np.array([-0.07, 0.00, 0]), np.array([-0.02, -0.06, 0]),
                 stroke_color="#7DC36A", stroke_width=2.2),
            Line(np.array([-0.02, -0.06, 0]), np.array([0.08, 0.06, 0]),
                 stroke_color="#7DC36A", stroke_width=2.2),
        )
        row = VGroup(marker, label_text).arrange(RIGHT, buff=0.16)
        step_rows.append(row)
        step_dots.append(marker)
        step_labels_mobs.append(label_text)
        step_checks.append(check)
    step_block = VGroup(*step_rows).arrange(DOWN, buff=0.10, aligned_edge=LEFT)
    step_block.move_to([CHAT_LEFT + 1.30 + step_block.width / 2,
                        THINK_HEAD_Y - 0.85, 0])
    # Move each step's check overlay to its marker's spot (after layout).
    for marker, check in zip(step_dots, step_checks):
        check.move_to(marker.get_center())

    # Visualisation pane — a thin wireframe rectangle that will hold
    # each step's content in turn. Sits to the right of the step list.
    viz_left_x   = step_block.get_right()[0] + 0.50
    viz_right_x  = CHAT_RIGHT - 0.30
    viz_w        = viz_right_x - viz_left_x
    viz_h        = (THINK_HEAD_Y - 0.25) - (CHAT_BOTTOM + 1.00)
    viz_ctr      = np.array([(viz_left_x + viz_right_x) / 2,
                             (CHAT_BOTTOM + 1.00 + THINK_HEAD_Y - 0.25) / 2, 0])
    viz_pane = RoundedRectangle(
        width=viz_w, height=viz_h, corner_radius=0.14,
        color=LINE, stroke_width=1.0, fill_opacity=0,
    ).move_to(viz_ctr)

    # ─────────────── BUILD: per-step viz content ───────────────────
    embed_group, query_dot, match_dots, q_lines, sim_labels, bg_dots, query_target = \
        _build_embedding_viz(rng, viz_ctr, viz_w - 0.50, viz_h - 0.50)
    summary_block = _build_summary_viz(summaries, viz_ctr, viz_w - 0.50, viz_h - 0.50)
    profile_block = _build_profile_viz(profile_spec, viz_ctr, viz_w - 0.50, viz_h - 0.50)
    compose_block, compose_frag_idx, compose_plus_idx = _build_compose_viz(
        fragments, viz_ctr, viz_w - 0.50, viz_h - 0.50)

    # ─────────────── BUILD: final answer bubble ─────────────────────
    # Avatar and bubble are vertically centred together — the same
    # layout convention as the user message above (mirrored side).
    # Build the bubble first to know its height, then place avatar at
    # the bubble's centre.
    # Wrap each highlighted fragment in <span foreground="…">.
    ai_markup = answer
    for h in highlights:
        ai_markup = ai_markup.replace(
            h, f'<span foreground="{HIGHLIGHT}">{h}</span>')
    ai_text = _high_dpi(MarkupText, ai_markup, 15, font="DejaVu Serif",
                        color=TEXT_BODY, line_spacing=1.0)
    ai_bubble = _wireframe_bubble(ai_text, pad_x=0.30, pad_y=0.22, min_w=5.5)
    ai_msg_group = VGroup(ai_bubble, ai_text)
    bubble_h = ai_msg_group.height
    # Place the bubble so its top sits with a small gap below the user
    # message (matches the spacing between user and AI in a real chat),
    # then put the avatar at the bubble's vertical centre.
    user_msg_bottom_y = user_msg_group.get_bottom()[1]
    bubble_top_y      = user_msg_bottom_y - 0.45
    answer_avatar_y   = bubble_top_y - bubble_h / 2
    ai_answer_avatar = _avatar_dot(
        AI_AVATAR_COLOR,
        np.array([CHAT_LEFT + 0.55, answer_avatar_y, 0]),
        radius=0.18,
    )
    ai_msg_group.move_to(
        [CHAT_LEFT + 0.95 + ai_msg_group.width / 2, answer_avatar_y, 0]
    )
    # Sanity: make sure the bubble's bottom clears the input divider
    # with a margin. If not, this is a layout bug — fail loud.
    bubble_bottom = ai_msg_group.get_bottom()[1]
    divider_top   = INPUT_Y + 0.45
    if bubble_bottom < divider_top + 0.30:
        raise RuntimeError(
            f"AI bubble ({bubble_bottom:.2f}) would overlap the input "
            f"divider ({divider_top:.2f}).")

    # Outro — title is large enough that Pango quantisation isn't an
    # issue, but the subtitle is small so go through the high-DPI path.
    title_text = Text(title, font="DejaVu Serif",
                      color=TEXT_HEAD, font_size=38)
    subtitle_text = _high_dpi(Text, subtitle, 20, font="DejaVu Serif",
                              slant=ITALIC, color="#9a9a9a")
    title_group = VGroup(title_text, subtitle_text).arrange(DOWN, buff=0.14)

    # ═══════════════ ANIMATE ═══════════════════════════════════════

    # ── ACT 1 ─ chat shell assembles
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
        Create(input_divider),
        FadeIn(input_box),
        FadeIn(send_group),
        FadeIn(input_placeholder),
        run_time=0.5,
    )
    scene.wait(0.25)

    # ── ACT 2 ─ user types the question
    scene.play(FadeOut(input_placeholder), run_time=0.15)
    scene.play(Write(question_text), run_time=1.6)
    scene.wait(0.2)

    # ── ACT 3 ─ Send pressed → user bubble appears
    scene.play(Indicate(send_group, color=AI_AVATAR_COLOR,
                         scale_factor=1.05), run_time=0.30)
    target_in_bubble = user_msg_text.get_center()
    scene.play(
        question_text.animate.move_to(target_in_bubble),
        FadeIn(user_bubble),
        FadeIn(user_avatar),
        run_time=0.7,
    )
    scene.remove(question_text)
    scene.add(user_msg_text)
    scene.wait(0.30)

    # ── ACT 4 ─ AI starts thinking
    scene.play(
        FadeIn(ai_think_avatar),
        FadeIn(think_header, shift=RIGHT * 0.1),
        run_time=0.6,
    )
    # Spin the ⟳ marker softly while we wait (one rotation).
    scene.play(Rotate(think_marker, angle=2*PI, about_point=think_marker.get_center()),
               run_time=0.9, rate_func=linear)

    # Step rows fade in as a dim placeholder list.
    scene.play(
        LaggedStart(*[FadeIn(r) for r in step_rows], lag_ratio=0.10),
        FadeIn(viz_pane),
        run_time=0.7,
    )
    scene.wait(0.20)

    # ── ACT 5 ─ four pipeline steps, each highlighted in turn

    def _activate_step(i):
        """Light up step i's marker + brighten its label."""
        return (
            step_dots[i].animate.set_color(MATCH_GLOW)
                                .set_fill(opacity=1.0)
                                .scale(1.35),
            step_labels_mobs[i].animate.set_color(TEXT_BODY),
        )

    def _complete_step(i):
        """Mark step i done: hide the dot, fade in a green tick at the
        same spot, dim the label."""
        return (
            step_dots[i].animate.set_fill(opacity=0),
            FadeIn(step_checks[i], scale=1.4),
            step_labels_mobs[i].animate.set_color(TEXT_DIM),
        )

    # ── Step 1: embedding scatter ───────────────────────────────
    scene.play(*_activate_step(0), run_time=0.35)
    # Build cloud (dots already at full opacity inside the viz_pane).
    scene.add(embed_group)
    # Re-make sure dots start invisible (we'll FadeIn them).
    for d in bg_dots:
        d.save_state()
        d.set_fill(opacity=0)
    for m in match_dots:
        m.save_state()
        m.set_fill(opacity=0)
    query_dot.save_state()
    query_dot.set_fill(opacity=0)
    # Reveal cloud
    scene.play(
        LaggedStart(*[d.animate.restore() for d in bg_dots], lag_ratio=0.01),
        run_time=0.9,
    )
    # Query vector lands at centre.
    scene.play(
        query_dot.animate.restore(),
        run_time=0.25,
    )
    scene.play(
        query_dot.animate.move_to(query_target),
        run_time=0.45,
    )
    # Beams + matches light up + sim numbers fade in.
    scene.play(
        *[ln.animate.set_stroke(opacity=0.75) for ln in q_lines],
        *[m.animate.restore() for m in match_dots],
        LaggedStart(*[s.animate.set_opacity(1) for s in sim_labels],
                    lag_ratio=0.10),
        run_time=0.85,
    )
    # Hold the embedding scatter — viewer wants to actually see the
    # 4 lit-up matches + their cosine sim numbers.
    scene.wait(1.6)
    # Complete step 1, fade out its viz to make room for step 2.
    scene.play(
        *_complete_step(0),
        FadeOut(embed_group),
        run_time=0.45,
    )

    # ── Step 2: summary list ─────────────────────────────────────
    scene.play(*_activate_step(1), run_time=0.35)
    scene.play(Write(summary_block), run_time=1.5)
    scene.wait(1.6)
    scene.play(
        *_complete_step(1),
        FadeOut(summary_block),
        run_time=0.45,
    )

    # ── Step 3: JSON profile ─────────────────────────────────────
    scene.play(*_activate_step(2), run_time=0.35)
    scene.play(Write(profile_block), run_time=2.0)
    scene.wait(1.6)
    scene.play(
        *_complete_step(2),
        FadeOut(profile_block),
        run_time=0.45,
    )

    # ── Step 4: compose ──────────────────────────────────────────
    scene.play(*_activate_step(3), run_time=0.35)
    # Three retrieved quote-fragments fade in first; the "+" signs
    # between them appear after to spell out that all of them feed
    # into the answer (not just the last one).
    fragment_mobs = [compose_block[i] for i in compose_frag_idx]
    plus_mobs     = [compose_block[i] for i in compose_plus_idx]
    scene.play(
        LaggedStart(*[FadeIn(f, shift=UP * 0.15) for f in fragment_mobs],
                    lag_ratio=0.20),
        run_time=1.0,
    )
    scene.play(
        LaggedStart(*[FadeIn(p, scale=1.4) for p in plus_mobs],
                    lag_ratio=0.20),
        run_time=0.5,
    )
    # Let the assembled "fragment + fragment + fragment" sit visibly
    # before everything flies toward the AI bubble.
    scene.wait(1.6)
    # Pull the whole stack toward where the answer's avatar will appear.
    answer_anchor = np.array([CHAT_LEFT + 1.2, answer_avatar_y, 0])
    scene.play(
        *[item.animate.move_to(answer_anchor).scale(0.6).set_opacity(0)
          for item in compose_block],
        run_time=0.85,
    )
    scene.play(*_complete_step(3), run_time=0.35)
    scene.wait(0.25)

    # ── ACT 6 ─ thinking area dissolves; AI answer types in
    thinking_all = VGroup(
        ai_think_avatar, think_header, step_block, viz_pane,
        *step_checks,
    )
    scene.play(
        FadeOut(thinking_all, shift=DOWN * 0.1),
        run_time=0.55,
    )
    scene.play(FadeIn(ai_answer_avatar), FadeIn(ai_bubble), run_time=0.5)
    scene.play(Write(ai_text), run_time=2.6)
    # Let the final answer breathe before the outro pulls focus off.
    scene.wait(2.6)

    # ── OUTRO ─ shift the chat up + title appears below
    full_chat = VGroup(
        chat_shell, user_avatar, user_msg_group,
        ai_answer_avatar, ai_msg_group,
    )
    scene.play(
        full_chat.animate.scale(0.82).shift(UP * 0.45),
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
            answer=ANSWER_RU,
            highlights=HIGHLIGHTS_RU,
            summaries=SUMMARIES_RU,
            profile_spec=PROFILE_JSON_RU,
            fragments=COMPOSE_FRAGMENTS_RU,
            think_label=THINK_LABEL_RU,
            step_labels=STEP_LABELS_RU,
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
            answer=ANSWER_EN,
            highlights=HIGHLIGHTS_EN,
            summaries=SUMMARIES_EN,
            profile_spec=PROFILE_JSON_EN,
            fragments=COMPOSE_FRAGMENTS_EN,
            think_label=THINK_LABEL_EN,
            step_labels=STEP_LABELS_EN,
            input_hint=INPUT_HINT_EN,
            send_label=SEND_EN,
            title=TITLE_EN,
            subtitle=SUBTITLE_EN,
        )
