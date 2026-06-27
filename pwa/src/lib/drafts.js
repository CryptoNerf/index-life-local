// Local-only unsaved-edit drafts. Keeps the in-progress rating + note safe
// across tab switches and even app restarts until the user taps Save. Stored
// in localStorage (tiny, synchronous, device-local) — never synced.

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
    localStorage.setItem(PREFIX + date, JSON.stringify({ rating, note }));
  } catch {
    /* storage full / disabled — drafting is best-effort */
  }
}

export function clearDraft(date) {
  try {
    localStorage.removeItem(PREFIX + date);
  } catch {
    /* ignore */
  }
}
