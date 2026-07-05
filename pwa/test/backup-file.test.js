// Backup/transfer file: importing must follow the same additive+LWW merge
// rules as cloud sync, so a file can never wipe or downgrade local data.
// (Also the browser→installed-PWA bridge on iOS, where the Home-Screen app
// gets a separate storage container from Safari.)

import 'fake-indexeddb/auto';
import { IDBFactory } from 'fake-indexeddb';
import { describe, it, expect, beforeEach } from 'vitest';
import { importBackupText } from '../src/lib/backup-file.js';
import { allEntries, putEntries } from '../src/lib/db.js';

function localStorageShim() {
  const m = new Map();
  return {
    getItem: (k) => (m.has(k) ? m.get(k) : null),
    setItem: (k, v) => m.set(k, String(v)),
    removeItem: (k) => m.delete(k)
  };
}

const entry = (date, over = {}) => ({
  uuid: `u-${date}`, date, rating: 7, note: 'x',
  created_at: '2026-07-01T00:00:00.000Z', updated_at: '2026-07-01T00:00:00.000Z',
  device_id: 'dev-a', deleted: false, ...over
});

const backup = (entries) => JSON.stringify({
  snapshot_version: 4, device_id: 'browser-1', mood_entries: entries
});

beforeEach(async () => {
  globalThis.localStorage = localStorageShim();
  globalThis.indexedDB = new IDBFactory(); // fresh, isolated DB per test
});

describe('importBackupText', () => {
  it('adds new days and reports the count', async () => {
    await putEntries([entry('2026-07-01')]);

    const r = await importBackupText(backup([entry('2026-07-02'), entry('2026-07-03')]));

    expect(r.added).toBe(2);
    expect(r.total).toBe(3);
    expect((await allEntries()).length).toBe(3);
  });

  it('never downgrades a newer local entry (LWW like cloud sync)', async () => {
    await putEntries([entry('2026-07-01', {
      note: 'local newer', updated_at: '2026-07-05T00:00:00.000Z'
    })]);

    await importBackupText(backup([entry('2026-07-01', { note: 'file older' })]));

    const all = await allEntries();
    expect(all[0].note).toBe('local newer');
  });

  it('skips invalid rows instead of failing the whole import', async () => {
    const r = await importBackupText(backup([
      entry('2026-07-01'),
      { date: 'not-a-date', rating: 5, deleted: false },
      { date: '2026-07-02', rating: 99, deleted: false }
    ]));

    expect(r.added).toBe(1);
  });

  it('rejects junk with a human message', async () => {
    await expect(importBackupText('не json')).rejects.toThrow(/не похож/);
    await expect(importBackupText('{"foo": 1}')).rejects.toThrow(/нет записей/);
  });
});
