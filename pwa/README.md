# index.life — PWA client

Phone-first Progressive Web App: capture + view your mood diary, local-first,
**no AI on-device** (the AI psychologist / neural map stay in the desktop app —
phones can't run the model; paid cloud compute may come much later).

Served as a static shell (e.g. GitHub Pages over HTTPS). Your data lives only on
your device (IndexedDB) and — in later milestones — syncs end-to-end-encrypted
through your own cloud. The cloud and GitHub Pages never see your data.

## Run

```bash
cd pwa
npm install
npm run dev        # local dev server
npm run build      # production build → dist/
npm run preview    # serve the built dist/
```

## Status — Milestone 1 (this scaffold)

- Installable PWA: web manifest + service worker (offline app shell), iOS
  "Add to Home Screen" meta.
- Brand-mobile UI (monochrome + Times serif accents, the mood-face line art)
  with a bottom nav and thumb-friendly targets.
- Capture: rate the day (1–10 cubes) + write a note → saved to IndexedDB.
- Feed: browse past days, tap to edit.
- Markdown export (native share sheet on phones, download fallback) — the
  always-available escape hatch so data is never locked in.
- "Protect storage" (`navigator.storage.persist()`) toward the
  never-lose-data guarantee.

### Next

- **M2** — crypto in JS (`libsodium.js`) + snapshot build/merge in JS, proven
  against the shared golden vectors and `docs/sync-spec/snapshot.schema.json`.
- **M3** — encrypted cloud transport (Dropbox / Google Drive / WebDAV) + full
  sync with the desktop + durability onboarding (persist + cloud + export).

## Layout

```
src/
  lib/        db.js (IndexedDB), mood.js, markdown.js
  components/ MoodFace, RatingCubes, BottomNav
  screens/    Capture, Feed, Settings
  App.svelte  shell + bottom-nav routing
```

The IndexedDB record mirrors a desktop snapshot's `mood_entries` item (date is
the merge identity; uuid/timestamps/deleted carried), so M2 sync merges with the
desktop under the same rules — see `../docs/sync-spec/`.
