// Shared reactive entries. Screens read `moodStore.entries` and update live
// when a save or a sync changes the data — no manual reload or tab switch.
// Kept out of the plain-JS sync engine (which stays headless-testable); the
// UI layer calls refreshEntries() after a sync.

import { allEntries, putEntry } from './db.js';

export const moodStore = $state({ entries: [], loaded: false });

export async function refreshEntries() {
  moodStore.entries = await allEntries();
  moodStore.loaded = true;
}

// Save a day and refresh the shared store so every screen reflects it.
export async function saveEntry(entry) {
  const rec = await putEntry(entry);
  await refreshEntries();
  return rec;
}
