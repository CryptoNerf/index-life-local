# Promo motion graphics

Manim scripts for the per-module promo intros. Each `.py` here is a
self-contained Manim scene that renders to MP4 — no proprietary tools,
no manual keyframing.

## One-time setup (macOS)

Manim depends on the Cairo C library (drawing), Pango (font rendering,
incl. Cyrillic), pkg-config (so the Python `pycairo` extension can
find Cairo at build time), and ffmpeg (the video encoder):

```bash
brew install cairo pango pkg-config ffmpeg
```

> Without `pkg-config` and `cairo`, `pip install manim` fails when
> building `pycairo` with errors like
> *"Did not find pkg-config"* /
> *"Run-time dependency cairo found: NO"*. The brew line above is the
> fix.

Then upgrade pip (newer pip handles meson-built wheels better) and
install Manim into the project venv (keeps your global Python clean):

```bash
./venv/bin/pip install --upgrade pip
./venv/bin/pip install manim
```

Linux / Windows: see <https://docs.manim.community/en/stable/installation.html>
(equivalent system packages exist on Debian/Ubuntu and via Chocolatey).

## Rendering

From the repo root:

```bash
./venv/bin/manim -qh promo/neural_map_intro.py NeuralMapIntro
```

The output lands in `media/videos/neural_map_intro/1080p60/NeuralMapIntro.mp4`
(`media/` is gitignored).

Quality flags:

| Flag | Resolution | Speed | When |
|---|---|---|---|
| `-ql` | 480p15 | very fast | iterating on timing/look |
| `-qm` | 720p30 | fast | preview before final |
| `-qh` | 1080p60 | minutes | promo-ready master |
| `-qk` | 4K60 | slow | only if you actually need 4K |

Add `-p` to auto-open the rendered file when done, e.g.
`manim -qh -p promo/neural_map_intro.py NeuralMapIntro`.

## Tweaking a scene

Common knobs live at the top of each script as named constants:

- **`PALETTE`** — list of HEX colours used for the per-cluster
  neurons. Reorder, add or remove to taste.
- **`TOPICS`** — `(name, position)` tuples. `name` is the Russian
  label; `position` is a `(x, y, 0)` manim coordinate in the default
  frame (~ -7.5..7.5 horizontally, -4..4 vertically).
- **`ENTRIES_PER_TOPIC`** — how many dots fly into each cluster.
  Vary the numbers to suggest topics of different "weight".

For deeper changes (timing, easing, camera moves) — each "ACT" block
in the scene's `construct()` is labelled and isolated; safe to nudge
one without touching the others.

## Scenes in this folder

| File | Scene class | Language | About |
|---|---|---|---|
| `neural_map_intro.py` | `NeuralMapIntro` | Russian | Diary entries drift together, coalesce into hidden-question neurons, get labelled, and link to nearest neighbours (~17 s) |
| `neural_map_intro.py` | `NeuralMapIntroEN` | English | Same motion, English labels and outro |
| `ai_psychologist_intro.py` | `AIPsychologistIntro` | Russian | Wireframe chat shell on black; user types and sends a question; the AI shows a "thinking" status and a 4-step pipeline runs inside the chat: a pseudo-3D embedding scatter with cosine-similarity beams to the 4 nearest neighbours, a monospace list of matching summaries with sim scores, a syntax-coloured JSON psychoprofile, and the highlighted fragments converging into the AI bubble that types the final answer with the quoted bits tinted amber (~24 s) |
| `ai_psychologist_intro.py` | `AIPsychologistIntroEN` | English | Same motion, English text |
| `ai_psychologist_intro_xray.py` | `AIPsychXRayIntro` / `…EN` | Both | Backup take of the AI psychologist promo — earlier "three layers x-rayed around the chat" approach. Kept for reference; the current production scene above replaces it. |
| `graphics_intro.py` | `GraphicsIntro` | Russian | A year of mood-diary entries (~300 dots, opacity coded by mood) morphs through four of the module's visualisations in turn: heatmap calendar → spiral year → weekday rose → mood river. Each dot keeps its identity through every transition — the whole point is "same data, many views" (~24 s) |
| `graphics_intro.py` | `GraphicsIntroEN` | English | Same motion, English captions and outro |
| `customization_intro.py` | `CustomizationIntro` | Russian | Four acts of customisation in turn: "index.life" appears in Times + brand cyan and each letter cycles through different fonts and colours with a cascade ("Кастомизируй шрифт"); twelve real app screenshots of the calendar under different bg presets crossfade through one after another ("Кастомизируй фон"); a 3×3 grid of chart pictograms covering all nine customisable charts (heatmap, spiral, rose, rhythm, ridgeline, words, river, activities, neural-map) cycles its accent colours every ~1 s ("Кастомизируй графики"); finally all three sit side by side under the title "Кастомизация" (~27 s). Bg screenshots live in `promo/customization_assets/` |
| `customization_intro.py` | `CustomizationIntroEN` | English | Same motion, English captions and outro |

Each scene file has a `_render_*(...)` helper holding the motion logic;
both languages call it with different text packs. Timing / colour /
layout edits there hit every language at once; only the text constants
differ.

Render either by class name:

```bash
./venv/bin/manim -qh -p promo/neural_map_intro.py NeuralMapIntro
./venv/bin/manim -qh -p promo/neural_map_intro.py NeuralMapIntroEN
./venv/bin/manim -qh -p promo/ai_psychologist_intro.py AIPsychologistIntro
./venv/bin/manim -qh -p promo/ai_psychologist_intro.py AIPsychologistIntroEN
```

More scenes to come, one per module.
