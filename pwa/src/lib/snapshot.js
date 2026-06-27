// Snapshot build + merge for the PWA — the JS twin of the desktop's
// app/sync.py build_snapshot() / apply_snapshot() (mood-entry side). Same v4
// shape (docs/sync-spec/snapshot.schema.json) and the same merge rules
// (additive + last-write-wins + tombstones, keyed by DATE) so the phone and the
// desktop converge identically. The PWA only authors mood_entries; other
// snapshot sections (derived AI data, chat) are desktop-produced and pass
// through untouched when present.

export const SNAPSHOT_VERSION = 4;

// ── build ────────────────────────────────────────────────────────────
export function buildSnapshot(entries, deviceId) {
  return {
    snapshot_version: SNAPSHOT_VERSION,
    device_id: deviceId,
    generated_at: new Date().toISOString(),
    mood_entries: entries.map((e) => ({
      uuid: e.uuid,
      date: e.date,
      rating: e.rating,
      note: e.note ?? null,
      created_at: e.created_at ?? null,
      updated_at: e.updated_at ?? null,
      device_id: e.device_id ?? deviceId,
      deleted: !!e.deleted
    }))
  };
}

// ── merge ────────────────────────────────────────────────────────────
const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;

// Mirrors _valid_mood: a row needs a YYYY-MM-DD date; a live (non-tombstone)
// row also needs an integer rating in 1..10. Invalid rows are skipped, never
// fatal.
export function validMood(d) {
  if (!d || typeof d !== 'object' || !DATE_RE.test(d.date)) return false;
  if (!d.deleted) {
    if (!Number.isInteger(d.rating) || d.rating < 1 || d.rating > 10) return false;
  }
  return true;
}

const ms = (s) => (s ? Date.parse(s) : NaN);

function inserted(p) {
  return {
    uuid: p.uuid,
    date: p.date,
    rating: p.rating != null ? p.rating : 1, // matches apply_snapshot default
    note: p.note ?? null,
    created_at: p.created_at ?? null,
    updated_at: p.updated_at ?? null,
    device_id: p.device_id ?? null,
    deleted: !!p.deleted
  };
}

// Merge a peer's mood_entries into the local set. Pure: returns a new array,
// does not mutate inputs. Identity is the date; a peer simply lacking a day is
// NOT a delete — only a `deleted:true` row with a newer updated_at removes one.
export function mergeMoodEntries(localEntries, peerEntries) {
  const byDate = new Map();
  for (const e of localEntries) byDate.set(e.date, e);

  for (const p of peerEntries || []) {
    if (!validMood(p)) continue;
    const local = byDate.get(p.date);
    if (!local) {
      byDate.set(p.date, inserted(p));
      continue;
    }
    const pUpd = ms(p.updated_at);
    const lUpd = ms(local.updated_at);
    // keep local unless the peer is STRICTLY newer (ties keep local)
    if (Number.isNaN(pUpd) || (!Number.isNaN(lUpd) && pUpd <= lUpd)) continue;

    if (p.deleted) {
      byDate.set(p.date, { ...local, deleted: true, updated_at: p.updated_at, device_id: p.device_id ?? null });
    } else {
      byDate.set(p.date, {
        ...local,
        rating: p.rating != null ? p.rating : local.rating,
        note: p.note ?? null,
        deleted: false,
        updated_at: p.updated_at,
        device_id: p.device_id ?? null
      });
    }
  }
  return [...byDate.values()];
}

// Merge a whole peer snapshot into local entries. A device never merges its
// own snapshot (matched by device_id, as on the desktop).
export function applySnapshot(localEntries, snapshot, ownDeviceId) {
  if (!snapshot || typeof snapshot !== 'object') return localEntries;
  if (snapshot.device_id && snapshot.device_id === ownDeviceId) return localEntries;
  return mergeMoodEntries(localEntries, snapshot.mood_entries);
}
