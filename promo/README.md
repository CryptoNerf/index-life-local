# Promo motion graphics

Manim scripts for the per-module promo intros. Each `.py` here is a
self-contained Manim scene that renders to MP4 — no proprietary tools,
no manual keyframing.

## One-time setup (macOS)

Manim needs Cairo, Pango (for fonts, incl. Cyrillic) and ffmpeg:

```bash
brew install py3cairo pango ffmpeg
```

Then install Manim itself into the project venv (keeps your global
Python clean):

```bash
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

| File | Scene class | About |
|---|---|---|
| `neural_map_intro.py` | `NeuralMapIntro` | Diary entries drift together, coalesce into topic-neurons, get names, and link to their nearest neighbours (~17 s) |

More to come, one per module.
