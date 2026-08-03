# index.life Design System

**index.life** is a local-first, privacy-first mood diary: a year of your life
as a grid of small squares, one per day, empty or filled. Two products share
one codebase and one visual language:

- **Desktop app** — Python/Flask + Jinja server-rendered pages, hand-written
  vanilla CSS, no framework, no build step. This is the primary target of this
  design system.
- **Mobile PWA** — Svelte, same visual language, referenced here for context
  (`pwa/`) but not yet built into a UI kit.

The whole identity rests on one idea: the day-grid heatmap calendar. Everything
else — settings pages, sync, account — is meant to feel like the same quiet
paper notebook the calendar lives in.

**Sources used to build this system** (read-only references; you may not have
access — ask the maintainer to re-share if you need to go deeper):
- GitHub: [CryptoNerf/index-life-local](https://github.com/CryptoNerf/index-life-local)
  (branch `index-qwen3.5`) — the ground truth for tokens, copy and layout.
  Look especially at `app/static/css/calendar.css`, `app/templates/mood_grid.html`,
  `app/static/css/sync.css`, `app/templates/sync.html`, and `app/translations/*.json`.
- Attached local codebase folders `templates/` and `css/` — the same Flask
  templates and stylesheets, provided directly for this project.

Explore the source repo further for anything this system doesn't cover yet —
the AI-psychologist, neural-map, graphics and customization modules, and the
Svelte PWA all live there.

## Index

- `styles.css` — root stylesheet, imports everything under `tokens/`.
- `tokens/colors.css`, `tokens/typography.css`, `tokens/spacing.css` — design tokens.
- `assets/` — logo mark (`icon.svg`, `apple-touch-icon.png`), favicons, the
  default profile-photo placeholder.
- `guidelines/` — foundation specimen cards (Colors, Type, Spacing, Brand groups).
- `components/` — reusable React primitives, grouped by concern:
  - `core/` — `PageNav`, `Section`, `Card`, `Marker`
  - `buttons/` — `PrimaryButton`, `SecondaryButton`
  - `feedback/` — `StatusBanner`, `InlineHint`, `EmptyState`
  - `forms/` — `ChoiceCard`, `FormRow` (+ `TextInput`), `FoldedDisclosure`
  - `sync/` — `StepCard`, `CodeQrBlock`, `DeviceRow`
- `ui_kits/desktop-app/` — an interactive recreation of the whole app on the
  design system: calendar (mood grid), day editor, life in weeks, account,
  sync (four states), modules, "what is index.life". Nav links switch pages,
  clicking a day cube opens the editor, and an RU/EN switch sits bottom-right
  so you can check that Russian labels fit.
- `handoff/` — production-ready output for the Flask app: `README.md`
  (step-by-step integration guide, in Russian, including prompts for Claude in
  VS Code), `_tokens.css` (the shared role tokens every page stylesheet should
  import), `sync.css` (drop-in replacement for `app/static/css/sync.css`) and
  `sync.partial.html` (the redesigned Jinja markup, with every existing form
  name, element id and JS hook preserved).
- `SKILL.md` — portable skill file for use in Claude Code or elsewhere.

## Intentional additions

One addition: **`Marker`** — a small square glyph in four states
(on / off / attention / active). It exists to replace the emoji the sync page
used as icons, and it is not a new shape: it is the day cube from the
calendar grid at 10px. Everything else has a direct counterpart in
`sync.css`/`sync.html` or the shared header/footer partials. No standard
"design-system" primitives (Toast, Tabs, Avatar, Dialog…) were added, because
the source app doesn't use them.

## Content fundamentals

- **Voice**: first person from the author, second person ("you"/"your") in the
  UI. Quiet and personal, never corporate. From the README: *"index.life —
  это идея того, что полезно иметь место в котором вы пишете что думаете и
  чувствуете о своём дне"* ("index.life is the idea that it's useful to have a
  place where you write what you think and feel about your day").
- **Casing**: sentence case everywhere, including buttons and headings
  (`Sync now`, not `SYNC NOW`). Never all-caps — Russian labels run longer and
  all-caps would make that worse.
- **No jargon in primary flows.** Words like "vault", "E2EE", "WebDAV",
  "conflict resolution", "snapshot" are banned from the main flow; they only
  appear inside a folded "advanced" area. The real strings show the discipline:
  `sync.folder_label` says "Sync folder (Dropbox, iCloud, Google Drive…)", not
  "configure your storage backend"; `sync.changes_heading` says "Changes from
  other devices", not "Conflicts" (the old, more technical label it replaced).
- **Reassuring, not alarming, about data safety.** `sync.disconnect_confirm`:
  "Disconnect sync on this device? Local data stays." Every destructive action
  explains in plain words what does *not* happen, before what does.
  `flash.rating_required`: "Please select your day mood rating (1-10) before
  saving" — direct, no scolding tone.
  `weather.privacy`: "Only an approximate location and date leave the device
  — to open-meteo.com, and only while weather is on." — privacy statements are
  specific about exactly what leaves the device, not vague reassurance.
- **No emoji in the target register.** The current `sync.html` uses emoji
  (📱💻🔒⚠️✅) as informal placeholder icons — the client has explicitly asked
  to remove these. Do not carry emoji into new work; see Iconography below for
  the replacement approach.
- **Bilingual RU/EN, written independently** (not machine-translated
  word-for-word) — Russian copy is often warmer/more personal than a literal
  translation of the English would be. Never assume equal string length.

## The two rules that keep pages consistent

The app's pages had drifted — headings were 20px on one screen, 22px on
another, 24px on a third, and vertical spacing was ad hoc. These two tables
are now the law. **Never write a raw px value for text size or spacing; always
reference a role token.**

### Type roles (`tokens/typography.css`)

| Role | Size | Used for |
|---|---|---|
| `--text-page-title` | 24px | the one `h1` per page |
| `--text-section-title` | 20px | `h2` — every section heading, every page |
| `--text-subhead` | 18px | status lines, step numbers, card titles |
| `--text-body` | 16px | body copy, buttons, inputs, choice labels |
| `--text-ui` | 14px | secondary/meta text, device rows, small buttons |
| `--text-hint` | 13px | hints and captions |
| `--text-nav` | 20px | the top nav |

Seven sizes exist (13 / 14 / 16 / 18 / 20 / 24 / 28) and nothing in between.
Headings are `font-weight: normal` — hierarchy comes from size and space, not
weight. 28px (`--text-display`) is reserved for the printed life-in-weeks sheet.

### Spacing roles (`tokens/spacing.css`)

| Role | Value | Used for |
|---|---|---|
| `--space-inline` | 8px | gap between buttons on one line |
| `--space-field` | 12px | label→input, marker→text |
| `--space-row` | 16px | between form rows, inside cards |
| `--space-block` | 24px | between blocks inside a section |
| `--space-section` | 48px | between sections; page top padding |
| `--space-page-bottom` | 64px | bottom of the content column |

Eight steps (4 / 8 / 12 / 16 / 24 / 32 / 48 / 64). Content column stays at
`--content-max-width: 640px`.

### Shape

`--radius: 0`. **The product has square corners.** The calendar, the day
cubes, the buttons, the inputs and the whole rest of the app have no rounded
corners, so nothing on a settings page may have them either — the 8px/12px
radii the old sync page used are gone. Separation is done with hairline
borders and space, never radius, never shadow.

## Visual foundations

- **Typography**: Times New Roman (system serif stack) everywhere — body,
  headings, buttons, form labels. No sans-serif UI font anywhere in the app.
  Monospace (`Courier New`) is reserved for codes/IDs: pairing codes, recovery
  keys, device IDs, backup filenames.
- **Color**: white background, near-black text (`#000`/`#222`), muted greys
  for secondary text (`#888`/`#666`/`#999`), and exactly **one** accent —
  brand blue `#009AFA` — used for the active nav link, focus rings, the
  "today" cube outline, and primary buttons. Semantic states use pale tints:
  warning `#fdf6e3` on amber `#e0c14a`, success `#f3faf3` on green `#d7e8d7`,
  never saturated banner colors.
- **Shape**: no shadows, no gradients, no glassmorphism, and no rounded
  corners — anywhere, on any page. Day cubes are always exactly square with a
  1px border; never round them or fill them decoratively — the grid *is* the
  brand, and every other block on screen echoes it.
- **Backgrounds**: flat white, full stop. No photography, no illustration, no
  repeating texture or pattern. (The optional "customization" module lets end
  users add a photo/gradient background or dark mode at runtime — everything
  themable is expressed as a CSS variable with a light-mode fallback so it
  still works when that happens.)
  All screens in this system use `var(--token, #fallback)` for every color
  that customization can touch — background, text, headings, muted text,
  brand, cube colors — never a bare hex value.
- **Animation**: none, beyond `transition: color/background/border 0.15–0.2s`
  on hover/focus. No entrance animation, no bounce, no page transitions.
- **Hover states**: links underline (no color shift beyond the existing brand
  blue for active); buttons darken slightly (`#000→#333`, brand
  `#009AFA→#007acc`); bordered cards/rows darken their border from a light
  grey toward `#999`/`#111`.
  Press states: none beyond the browser default — no scale/shrink effects
  except the day-editor's formatting toolbar buttons (`scale(0.95)` on
  `:active`), which is local to that one screen, not a system-wide pattern.
- **Borders**: hairline throughout — `#e0e0e0`, `#ddd`, `#d8d8d8`, `#f0f0f0`
  depending on context — never more than 1px except focus/today indicators
  (2px) and destructive/danger outlines.
  Inner/outer shadow systems: none exist; don't introduce one.
  Transparency/blur: not used — the one exception is disabled-state opacity
  (buttons, cubes) and a hover opacity dip (0.7) on the day-rating cubes.
- **Layout**: single column, `max-width: 640px`, centered, generous vertical
  rhythm via hairline-divided `<section>` blocks with 24–40px of breathing
  room. No sidebars, no multi-column dashboards, no fixed/sticky chrome except
  the top nav (which is not fixed-position, just always first in flow).
- **Imagery**: none in the UI itself — the only images are the app icon/mark
  and a generic no-photo placeholder avatar. Any "imagery" in the product is
  user-uploaded (profile photo, custom background), never brand-supplied.

## Iconography

- **No icon font, no SVG icon set, no PNG icon sprite exists in the
  codebase.** The only graphic assets are the app icon/logo and generic
  favicons — there is no icon library to draw from.
- **Current state (to move away from)**: `sync.html` uses emoji as
  informal stand-ins for phone/laptop/lock/warning/checkmark
  (📱💻🔒⚠️✅🔑☁️). The client dislikes this and asked for something quieter.
- **The replacement, now built: the square `Marker`.** Instead of importing an
  icon set, the system uses the brand's own shape — the day cube — at 10–12px,
  in four states: filled (on/synced/selected), outline (off/not set up), amber
  (needs attention), blue outline (current, matching the "today" cube). It
  pairs with a text label and never carries meaning alone. This keeps the page
  iconless while still giving each line a scannable left edge.
  See `guidelines/brand-iconography.html` and `components/core/Marker.jsx`.
  Plain text labels remain the first choice — "Connect your phone", not a
  phone glyph.
- Unicode symbols are used sparingly and functionally, not decoratively: `←`/`→`
  for year navigation, `✓`/`✗` for pass/fail test results (in `#2a8f2a`/`#c0392b`,
  not emoji). These read as typographic marks, not icons, and fit the register.

## Caveats & how to help iterate

- **Iconography is solved with the square `Marker`, not with drawn icons.**
  If you'd rather have real line glyphs (phone / computer / lock), say so and
  point me at a set whose stroke weight you like — I won't invent one silently.
- **The other pages still need migrating** to the type and spacing role
  tokens. `handoff/sync.css` shows exactly how (it carries a copy of the role
  variables in `:root`); once you're happy with it, those `--il-*` variables
  should move into a shared `_tokens.css` that every page stylesheet imports,
  and account / modules / calendar should be switched over to the same roles.
  That's the change that actually stops headings drifting between screens.
- **Only the desktop app got a UI kit.** All seven of its pages are drawn, but
  the PWA (Svelte) shares the brand and has its own component set
  (`pwa/src/components/`) I only skimmed — say the word and I'll build a
  matching mobile UI kit next.
- **Logo**: the only mark I found is the 3×3 grid glyph (`assets/icon.svg`,
  `assets/apple-touch-icon.png`) — I used it as-is and did not redraw or
  extend it. If there's a separate wordmark lockup somewhere, share it and
  I'll fold it in.
- This system covers the **sync page component set** you asked for first.
  Modules pages, account, life-in-weeks and the customization panel reuse the
  same `Card`/`Section`/`FoldedDisclosure` primitives but weren't turned into
  their own UI-kit screens — say which one to do next.

I'd love your read on the four sync-page states in `ui_kits/desktop-app/` —
tell me what's off and I'll iterate.
