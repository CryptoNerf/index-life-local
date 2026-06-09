# Customization

[← back to index](../README.md) · [Русский](../ru/customization.md)

**Promo video** ([download](../videos/customization-en.mp4)):

<video src="../videos/customization-en.mp4" controls width="720"></video>

The Customization module changes the app's appearance. Changes apply instantly to the whole interface and to the mini-preview beside each section. There are **"Save"** and **"Reset"** buttons (plus per-section reset).

Technically: settings are stored as JSON in `user_customization`, and the app emits them on every page as an inline `<style>` block of CSS variables — so changes don't depend on the browser cache and show up immediately.

---

## What you can customize

![Customization settings with live preview](../images/customize.png)

![The app after customization](../images/after-customize.png)

- **Page background** — a solid color, a gradient, or your own image (with blur and opacity). Applies instantly for all three types.
- **Fonts** — separately for body text and headings. All fonts are bundled locally (the app works offline); you can upload your own `.ttf/.otf/.woff/.woff2` file (up to 5 MB). The "Apply body font to diary notes" option extends the font to the note editor.
- **Text & accent** — body text color, muted (secondary) text, heading color, accent (active link).
- **Auto-invert text** — recomputes the text color against the background's brightness so it stays readable on a dark background.
- **Calendar** — cube colors: filled day, empty day, border, "today" highlight.
- **Calendar mosaic** — "spread" an image across the whole calendar: each cube is a window into its piece. Empty days can show a color, a gradient, or a second image that "reveals" itself as days fill in.
- **Graphics** — a global color for all charts plus **per-chart settings** (each its own subsection with a live preview): river, spiral, rose, ridgeline, rhythm, overview, activities.
- **Neural map** — colors for neurons, the active neuron, links, and the canvas background.

---

## Storage cleanup

Uploaded images and fonts live in `customization_uploads/`. If you experimented with different backgrounds, old files stay on disk. At the bottom of the page there's "Storage cleanup": it lists "orphan" files (no longer referenced) and removes them on confirmation.

---

## Theme export/import

A theme can be exported to a JSON file and loaded back ("Export"/"Import" buttons) — handy for moving your look between devices or sharing. On import, values are checked by the same validators as on save, so a malformed file can't smuggle in bad styles.
