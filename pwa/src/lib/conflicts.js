// Versions of your own entries that a sync replaced.
//
// Merging is last-write-wins by date, so when the same day was edited here
// and on another device, one version loses. The desktop has always kept the
// loser in a 30-day log ("Changes from other devices"); the phone threw it
// away — the text simply vanished, with nothing to look at and nothing to
// blame. That is the worst failure a diary can have, and it happens for
// mundane reasons: a phone clock a couple of minutes behind, or an edit made
// offline while the same day was touched on the desktop.
//
// Storage is localStorage (small, survives an IndexedDB eviction, and this
// log is device-local by nature — it is about what happened *here*).

const KEY = 'indexlife:conflicts';
const SEEN_KEY = 'indexlife:conflicts-seen';
const KEEP_MS = 30 * 24 * 60 * 60 * 1000;  // same window as the desktop
const MAX_ROWS = 200;

function read() {
  try {
    const raw = JSON.parse(localStorage.getItem(KEY) || '[]');
    return Array.isArray(raw) ? raw : [];
  } catch {
    return [];
  }
}

function write(rows) {
  try {
    localStorage.setItem(KEY, JSON.stringify(rows));
  } catch {
    /* quota / private mode — the log is a nicety, never a blocker */
  }
}

// Drop rows older than the window, newest first, bounded.
function prune(rows, now = Date.now()) {
  return rows
    .filter((r) => r && r.at && now - r.at < KEEP_MS)
    .sort((a, b) => b.at - a.at)
    .slice(0, MAX_ROWS);
}

/**
 * Record the local versions a merge replaced.
 * `losers` items: { date, rating, note, updated_at, peerDevice }.
 */
export function recordConflicts(losers, now = Date.now()) {
  if (!losers || !losers.length) return 0;
  const rows = read();
  for (const l of losers) {
    rows.push({
      at: now,
      date: l.date,
      rating: l.rating ?? null,
      note: l.note ?? null,
      updated_at: l.updated_at ?? null,
      peer: l.peerDevice || null
    });
  }
  write(prune(rows, now));
  return losers.length;
}

export function listConflicts() {
  return prune(read());
}

// "Seen" is a timestamp: rows newer than it are what the user hasn't been
// told about yet. A count rather than per-row flags keeps the storage tiny.
export function unseenCount() {
  const seen = Number(localStorage.getItem(SEEN_KEY)) || 0;
  return listConflicts().filter((r) => r.at > seen).length;
}

export function markSeen() {
  try {
    localStorage.setItem(SEEN_KEY, String(Date.now()));
  } catch {
    /* best-effort */
  }
}

export function clearConflicts() {
  try {
    localStorage.removeItem(KEY);
  } catch {
    /* best-effort */
  }
}

// Drop one row once its content has been restored (or dismissed), so the
// list reflects what still needs attention.
export function forgetConflict(at, date) {
  write(read().filter((r) => !(r.at === at && r.date === date)));
}
