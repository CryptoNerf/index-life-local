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
| `ai_psychologist_intro.py` | `AIPsychologistIntro` | Russian | A diary question rises through 4 memory layers (entries → embeddings → summaries → psychological profile), fragments fly into the answer, quotes from real entries highlight (~22 s) |
| `ai_psychologist_intro.py` | `AIPsychologistIntroEN` | English | Same motion, English answer + layer labels |

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
