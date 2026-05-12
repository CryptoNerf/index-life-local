# Customization module

Lets the user theme the entire app: colours, fonts, page background,
calendar mosaic. Sentinel-activated, no Python deps required, fully
offline (bundled web fonts, locally-stored uploads).

## Layout

```
customization/
├── __init__.py            Blueprint, sentinel, init_app, uploads_dir()
├── routes.py              All HTTP endpoints (page, save/reset, upload, export/import, cleanup)
├── defaults.py            Single source of truth for the customization keys
├── fonts_catalog.py       Bundled font catalog (id → label → css family)
├── context_processor.py   Emits the inline <link>+<style>+<script> markup on every page
├── templates/customization/settings.html    Settings UI
├── static/
│   ├── css/settings.css   UI of the settings page itself
│   ├── js/settings.js     UI logic (live preview, save/reset, upload, import/export)
│   ├── js/mosaic.js       Per-cube background-position painter for the diary calendar
│   └── fonts/             Bundled woff2 files + fonts.css + manifest/catalog JSON
└── README.md              this file
```

## Key concepts

### Zero visual drift

When the module is installed but the user has not changed anything,
the rendered HTML must be **byte-identical** (modulo a marker tag and
nav link) to the inactive-module render. The mechanism:

1. Every themable CSS rule uses `var(--name, original-value)`. The
   *original* hard-coded value is the fallback, so when no CSS variable
   is set the page looks exactly as it did before customization existed.

2. `context_processor._emit_css_block` only emits CSS variables for
   keys the user has *changed*. An empty/default settings row produces
   `<style id="customization-vars"></style>` — no rules at all.

3. `defaults.DEFAULTS` is the authoritative *schema* (set of allowed
   keys); the values inside it are picker initial values for the UI,
   not authoritative defaults for the live page rendering.

The `tests/test_customization_drift.py` snapshot test would normally
guard this — currently the check lives in the development scripts.

### Composite vs raw keys

Some user-facing settings translate 1:1 to a CSS variable
(`brand-color`, `cube-filled-color`). Others are *metadata* the
context processor combines into a derived CSS value:

| User keys (metadata)                                                     | Derived CSS variable      |
|--------------------------------------------------------------------------|---------------------------|
| `bg-type`, `bg-color`, `bg-gradient-from/to/angle`, `bg-image-filename`  | `--bg-image`              |
| `font-body-id`, `custom-font-filename`                                   | `--font-body`             |
| `font-heading-id`                                                        | `--font-heading`          |
| `notes-use-body-font`                                                    | `--font-notes`            |
| `mosaic-*` (all of them)                                                 | `window.__CZ_MOSAIC__` JSON|

`_METADATA_KEYS` lists which keys must NOT be emitted as raw CSS
variables, so a typo in the JSON doesn't end up as a stray
`--bg-type: image` rule on the page.

### Adding a new themable surface

1. Add the new key + sensible default value to `DEFAULTS` in
   `defaults.py`.
2. Register a validator in `_VALIDATORS` in `routes.py` (use one of
   the existing `_is_valid_*` helpers, or add a new one if it's a new
   value shape).
3. Update the relevant CSS rule(s) to read `var(--your-key, original)`.
4. Add a control to `templates/customization/settings.html` and wire
   it up in `static/js/settings.js`.
5. If the new key belongs to an existing settings section, add it to
   the matching `_SECTION_KEYS` entry so per-section reset clears it.
6. (Optional) Update the live mini-preview on the settings page to
   reflect the new variable.

## Endpoints

| Path                                        | Purpose                              |
|---------------------------------------------|--------------------------------------|
| `GET  /customization/`                      | Settings page                        |
| `GET  /customization/api/settings`          | Effective settings (defaults+overrides) |
| `POST /customization/api/save`              | Patch saved settings                 |
| `POST /customization/api/reset`             | Reset all to defaults                |
| `POST /customization/api/reset-section`     | Reset one section's keys             |
| `POST /customization/api/upload-bg`         | Upload an image (bg / mosaic)        |
| `POST /customization/api/upload-font`       | Upload a custom font file            |
| `POST /customization/api/delete-bg`         | Forget the current bg image filename |
| `GET  /customization/api/fonts`             | Bundled font catalog                 |
| `GET  /customization/api/export`            | Download theme as JSON               |
| `POST /customization/api/import`            | Replace theme from JSON              |
| `GET  /customization/api/orphan-uploads`    | List uploaded files no longer used   |
| `POST /customization/api/cleanup-orphans`   | Delete those files                   |
| `GET  /customization/uploads/<name>`        | Serve user upload (strict regex)     |

## Storage

- Settings JSON: a single row in the `user_customization` table
  (`models.UserCustomization`), schema migration v6 in `app/__init__.py`.
- Uploads: `<user data dir>/customization_uploads/`, accessed via
  `customization.uploads_dir()`. Filenames are random hex tokens, so
  no path traversal possible. Resolved via the strict `_FILENAME_RE`
  / `_FONT_FILENAME_RE` regexes before serving.

## Bundled fonts

`static/fonts/fonts.css` is generated alongside the woff2 files.
Each `@font-face` rule uses `size-adjust:` so all bundled fonts
visually match Times' x-height at the same `font-size`. Variable-font
woff2 files are deduplicated: one physical file backs multiple
@font-face blocks at different weights.

To add a font:

1. Drop the `.woff2` files in `static/fonts/`.
2. Add a `@font-face` block to `static/fonts/fonts.css` (with
   `size-adjust:` matching x-height ≈ 0.448em).
3. Add an entry to `FONT_CATALOG` in `fonts_catalog.py`.

## Disabling the module

Sentinel file (`<user data dir>/customization_enabled`) is the on/off
switch — same pattern as `insights` and `deep_mind`. Removing the
sentinel deactivates the module on next app restart. The DB row and
upload directory are kept untouched, so re-enabling restores
everything.
