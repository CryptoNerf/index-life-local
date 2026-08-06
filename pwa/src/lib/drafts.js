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

// What the day editor should show for a date, given the stored entry and any
// draft. Lives here rather than in the screen so the rules are testable.
//
// The tombstone case is the subtle one: a deleted day keeps its old text (the
// deletion travels to peers that still hold the entry), so feeding it to the
// editor would show content the user deliberately deleted on another device —
// and saving would push it back, resurrecting it. A draft still wins: text
// typed here and never saved is the user's own, whatever the sync says.
export function editorStateFor(entry, draft) {
  const fresh = draftIsFresh(draft, entry) ? draft : null;
  const live = entry && !entry.deleted ? entry : null;
  return {
    rating: fresh?.rating ?? live?.rating ?? 0,
    note: fresh?.note ?? live?.note ?? '',
    deletedElsewhere: !!entry?.deleted && !fresh
  };
}

export function clearDraft(date) {
  try {
    localStorage.removeItem(PREFIX + date);
  } catch {
    /* ignore */
  }
}
