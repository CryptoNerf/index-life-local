// Local-only unsaved-edit drafts. Keeps the in-progress rating + note safe
// across tab switches and even app restarts until the user taps Save. Stored
// in localStorage (tiny, synchronous, device-local) — never synced.

import { toEpochMs } from './snapshot.js';

const PREFIX = 'indexlife:draft:';

export function loadDraft(date) {
  try {
    const raw = localStorage.getItem(PREFIX + date);
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

export function saveDraft(date, { rating, note }) {
  try {
    localStorage.setItem(PREFIX + date, JSON.stringify({ rating, note, at: Date.now() }));
  } catch {
    /* storage full / disabled — drafting is best-effort */
  }
}

// A draft only wins over the saved entry while it is the FRESHER of the two.
// Scenario guarded against: type on the phone without saving, then edit the
// same day on the desktop and sync — the stale phone draft must not hide
// (and, on Save, overwrite) the newer synced entry. Drafts written before
// the `at` field existed count as age-unknown and lose to any timestamped
// entry; an entry without a parseable updated_at never beats a draft.
export function draftIsFresh(draft, entry) {
  if (!draft) return false;
  if (!entry) return true;
  const entryAt = toEpochMs(entry.updated_at);
  if (Number.isNaN(entryAt)) return true;
  return (draft.at ?? 0) >= entryAt;
}

export function clearDraft(date) {
  try {
    localStorage.removeItem(PREFIX + date);
  } catch {
    /* ignore */
  }
}
