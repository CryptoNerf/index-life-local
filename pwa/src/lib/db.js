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
