// Local-first storage for the PWA — IndexedDB, one record per calendar day.
//
// The record shape mirrors a desktop snapshot's `mood_entries` item (date is
// the merge identity; uuid/created_at/updated_at/deleted are carried) so that
// when encrypted cloud sync lands (M2/M3) these rows merge with the desktop
// under the same last-write-wins rules — no schema translation needed.

const DB_NAME = 'indexlife';
const STORE = 'entries';
const VERSION = 1;

function openDB() {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(DB_NAME, VERSION);
    req.onupgradeneeded = () => {
      const db = req.result;
      if (!db.objectStoreNames.contains(STORE)) {
        db.createObjectStore(STORE, { keyPath: 'date' });
      }
    };
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

// One request per transaction — never await other promises mid-transaction,
// or IndexedDB auto-commits and the store goes inactive.
async function store(mode) {
  const db = await openDB();
  return db.transaction(STORE, mode).objectStore(STORE);
}

function asPromise(request) {
  return new Promise((resolve, reject) => {
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}

export async function getEntry(date) {
  const s = await store('readonly');
  return (await asPromise(s.get(date))) || null;
}

export async function allEntries() {
  const s = await store('readonly');
  return (await asPromise(s.getAll())) || [];
}

export async function putEntry({ date, rating, note }) {
  const existing = await getEntry(date);
  const now = new Date().toISOString();
  const rec = {
    date,
    rating,
    note: note ?? '',
    uuid: existing?.uuid || crypto.randomUUID(),
    created_at: existing?.created_at || now,
    updated_at: now,
    deleted: false
  };
  const s = await store('readwrite');
  await asPromise(s.put(rec));
  return rec;
}

// Persist a batch of entries (the result of a sync merge) in one transaction.
// Each record is keyed by date, so this upserts the merged state as-is.
export async function putEntries(entries) {
  if (!entries.length) return;
  const s = await store('readwrite');
  await Promise.all(entries.map((e) => asPromise(s.put(e))));
}

// Ask the browser to keep our data from being evicted under storage pressure.
// Returns true if storage is now persistent. Part of the "never silently lose
// data" guarantee for phone-only users (alongside cloud sync + markdown export).
export async function requestPersist() {
  if (navigator.storage?.persist) return navigator.storage.persist();
  return false;
}

export async function isPersisted() {
  if (navigator.storage?.persisted) return navigator.storage.persisted();
  return false;
}

// ── localStorage mirror (second same-device copy) ────────────────────
// IndexedDB and localStorage are evicted/corrupted independently, and
// IndexedDB has historically been the more fragile of the two on iOS.
// The diary is small text, so mirroring every refresh gives a same-device
// fallback that survives an IndexedDB wipe — one more layer of the
// "ratings must not vanish even with no cloud" guarantee. Best-effort:
// silently skipped when the diary outgrows the quota guard.

const MIRROR_KEY = 'indexlife:mirror';
const MIRROR_MAX_CHARS = 3_500_000; // ~7 MB UTF-16 — under browser quotas

export function mirrorEntries(entries) {
  try {
    const json = JSON.stringify(entries);
    if (json.length > MIRROR_MAX_CHARS) return;
    localStorage.setItem(MIRROR_KEY, json);
  } catch {
    /* quota full / storage disabled — best-effort */
  }
}

// If IndexedDB came up EMPTY but the mirror has data (eviction/corruption),
// restore from the mirror. Returns the number of restored entries.
export async function restoreFromMirrorIfEmpty() {
  try {
    const existing = await allEntries();
    if (existing.length) return 0;
    const raw = localStorage.getItem(MIRROR_KEY);
    if (!raw) return 0;
    const entries = JSON.parse(raw);
    if (!Array.isArray(entries) || !entries.length) return 0;
    await putEntries(entries);
    return entries.length;
  } catch {
    return 0;
  }
}
