// localStorage mirror — the second same-device copy that survives an
// IndexedDB wipe/eviction (part of the "ratings must not vanish even with
// no cloud" guarantee).

import 'fake-indexeddb/auto';
import { IDBFactory } from 'fake-indexeddb';
import { describe, it, expect, beforeEach } from 'vitest';
import {
  allEntries, putEntries, mirrorEntries, restoreFromMirrorIfEmpty
} from '../src/lib/db.js';

function localStorageShim() {
  const m = new Map();
  return {
    getItem: (k) => (m.has(k) ? m.get(k) : null),
    setItem: (k, v) => m.set(k, String(v)),
    removeItem: (k) => m.delete(k)
  };
}

const entry = (date) => ({
  uuid: `u-${date}`, date, rating: 7, note: 'x',
  created_at: '2026-07-01T00:00:00.000Z', updated_at: '2026-07-01T00:00:00.000Z',
  deleted: false
});

beforeEach(() => {
  globalThis.localStorage = localStorageShim();
  globalThis.indexedDB = new IDBFactory(); // fresh, isolated DB per test
});

describe('localStorage mirror', () => {
  it('restores entries after IndexedDB was wiped', async () => {
    const entries = [entry('2026-07-01'), entry('2026-07-02')];
    mirrorEntries(entries);
    globalThis.indexedDB = new IDBFactory();        // "eviction": empty DB

    const restored = await restoreFromMirrorIfEmpty();

    expect(restored).toBe(2);
    expect((await allEntries()).length).toBe(2);
  });

  it('never overwrites a non-empty IndexedDB', async () => {
    await putEntries([entry('2026-07-01')]);
    mirrorEntries([entry('2026-07-02'), entry('2026-07-03')]);   // stale mirror

    const restored = await restoreFromMirrorIfEmpty();

    expect(restored).toBe(0);
    expect((await allEntries()).length).toBe(1);     // untouched
  });

  it('is a no-op when there is no mirror', async () => {
    expect(await restoreFromMirrorIfEmpty()).toBe(0);
  });

  it('skips oversized diaries instead of throwing', () => {
    const huge = [{ ...entry('2026-07-01'), note: 'x'.repeat(4_000_000) }];
    expect(() => mirrorEntries(huge)).not.toThrow();
    expect(localStorage.getItem('indexlife:mirror')).toBe(null);
  });
});
