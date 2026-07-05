// Shared reactive entries. Screens read `moodStore.entries` and update live
// when a save or a sync changes the data — no manual reload or tab switch.
// Kept out of the plain-JS sync engine (which stays headless-testable); the
// UI layer calls refreshEntries() after a sync.

import {
  allEntries, putEntry, mirrorEntries, restoreFromMirrorIfEmpty,
  isPersisted, requestPersist,
} from './db.js';

export const moodStore = $state({ entries: [], loaded: false });

export async function refreshEntries() {
  let entries = await allEntries();
  if (!entries.length) {
    // IndexedDB empty but the localStorage mirror has data — an eviction
    // or corruption happened; restore the second copy transparently.
    const restored = await restoreFromMirrorIfEmpty();
    if (restored) entries = await allEntries();
  }
  moodStore.entries = entries;
  moodStore.loaded = true;
  // Keep the mirror fresh after every change (saves AND sync merges all
  // funnel through here).
  mirrorEntries(entries);
}

// Ask for durable storage once, right after the first save — the moment
// of clearest user engagement, when browsers are most likely to grant it.
// The Durability screen keeps a manual button in case this is denied.
const PERSIST_ASKED_KEY = 'indexlife:persist-asked';

async function autoPersist() {
  try {
    if (await isPersisted()) return;
    if (localStorage.getItem(PERSIST_ASKED_KEY)) return;
    localStorage.setItem(PERSIST_ASKED_KEY, '1');
    await requestPersist();
  } catch {
    /* best-effort */
  }
}

// Save a day and refresh the shared store so every screen reflects it.
export async function saveEntry(entry) {
  const rec = await putEntry(entry);
  await refreshEntries();
  autoPersist();
  return rec;
}
