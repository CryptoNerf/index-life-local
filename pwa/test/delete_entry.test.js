// Deleting a day on the phone.
//
// The phone could write and edit but never delete — a whole basic action
// missing for someone who lives in the app on their phone. The delete has to
// be a SOFT one: removing the record would let any device that still holds
// the entry send it back on the next merge, because the merge only treats a
// newer `deleted: true` row as a deletion and a missing row as nothing at all.

import { describe, it, expect, beforeEach } from 'vitest';
import { IDBFactory } from 'fake-indexeddb';
import { getEntry, putEntry, deleteEntry, allEntries } from '../src/lib/db.js';
import { mergeMoodEntries, buildSnapshot } from '../src/lib/snapshot.js';

beforeEach(() => {
  // A fresh database per test — fake-indexeddb keeps state on the factory.
  globalThis.indexedDB = new IDBFactory();
});

describe('deleteEntry', () => {
  it('leaves a tombstone that still carries the text', async () => {
    await putEntry({ date: '2026-07-01', rating: 8, note: 'хороший день' });
    const tomb = await deleteEntry('2026-07-01');

    expect(tomb.deleted).toBe(true);
    expect(tomb.rating).toBe(8);
    expect(tomb.note).toBe('хороший день');

    // The row is still there — that is what carries the deletion to peers.
    const stored = await getEntry('2026-07-01');
    expect(stored.deleted).toBe(true);
    expect(await allEntries()).toHaveLength(1);
  });

  it('keeps the uuid so the two sides still mean the same entry', async () => {
    const saved = await putEntry({ date: '2026-07-01', rating: 8, note: 'x' });
    const tomb = await deleteEntry('2026-07-01');
    expect(tomb.uuid).toBe(saved.uuid);
  });

  it('stamps a newer updated_at, so the deletion wins the merge', async () => {
    const saved = await putEntry({ date: '2026-07-01', rating: 8, note: 'x' });
    await new Promise((r) => setTimeout(r, 5));
    const tomb = await deleteEntry('2026-07-01');
    expect(Date.parse(tomb.updated_at)).toBeGreaterThan(Date.parse(saved.updated_at));
  });

  it('does nothing for a day that was never written', async () => {
    expect(await deleteEntry('2026-07-09')).toBe(null);
  });

  it('does nothing for a day already deleted', async () => {
    await putEntry({ date: '2026-07-01', rating: 8, note: 'x' });
    await deleteEntry('2026-07-01');
    expect(await deleteEntry('2026-07-01')).toBe(null);
  });

  it('saving the day again revives it', async () => {
    await putEntry({ date: '2026-07-01', rating: 8, note: 'первая версия' });
    await deleteEntry('2026-07-01');
    const revived = await putEntry({ date: '2026-07-01', rating: 6, note: 'снова' });

    expect(revived.deleted).toBe(false);
    expect((await getEntry('2026-07-01')).deleted).toBe(false);
  });
});

describe('undo', () => {
  // What store.restoreEntry does: the tombstone still carries the rating and
  // the note, so bringing a day back needs no second copy of the text.
  it('brings the day back with its original content', async () => {
    await putEntry({ date: '2026-07-01', rating: 8, note: 'хороший день' });
    await deleteEntry('2026-07-01');

    const tomb = await getEntry('2026-07-01');
    const revived = await putEntry({
      date: '2026-07-01', rating: tomb.rating, note: tomb.note
    });

    expect(revived.deleted).toBe(false);
    expect(revived.rating).toBe(8);
    expect(revived.note).toBe('хороший день');
    expect(revived.uuid).toBe(tomb.uuid);   // still the same entry
  });

  it('stamps the revival as newer than the deletion, so it wins elsewhere', async () => {
    await putEntry({ date: '2026-07-01', rating: 8, note: 'x' });
    const tomb = await deleteEntry('2026-07-01');
    await new Promise((r) => setTimeout(r, 5));
    const revived = await putEntry({ date: '2026-07-01', rating: 8, note: 'x' });

    expect(Date.parse(revived.updated_at)).toBeGreaterThan(Date.parse(tomb.updated_at));

    // A peer still holding the tombstone must accept the revival.
    const merged = mergeMoodEntries([{ ...tomb }], [revived]);
    expect(merged[0].deleted).toBe(false);
  });
});

describe('the deletion reaches other devices', () => {
  it('travels in the snapshot the phone publishes', async () => {
    await putEntry({ date: '2026-07-01', rating: 8, note: 'x' });
    await deleteEntry('2026-07-01');

    const snap = buildSnapshot(await allEntries(), 'dev-phone', 'Телефон');
    const row = snap.mood_entries.find((e) => e.date === '2026-07-01');
    expect(row.deleted).toBe(true);
    expect(row.uuid).toBeTruthy();
  });

  it('a peer that still holds the day takes the deletion', async () => {
    await putEntry({ date: '2026-07-01', rating: 8, note: 'x' });
    const tomb = await deleteEntry('2026-07-01');

    // The desktop's copy, written before the delete.
    const desktop = [{
      uuid: tomb.uuid, date: '2026-07-01', rating: 8, note: 'x',
      updated_at: '2026-07-01T09:00:00', deleted: false
    }];
    const merged = mergeMoodEntries(desktop, [{ ...tomb }]);
    expect(merged[0].deleted).toBe(true);
  });

  it('a peer holding the OLD live copy cannot resurrect it', async () => {
    // The exact failure a hard delete would cause: our row is gone, the peer
    // still has the entry, and the next merge quietly brings the day back.
    await putEntry({ date: '2026-07-01', rating: 8, note: 'x' });
    const tomb = await deleteEntry('2026-07-01');

    const stalePeer = [{
      uuid: tomb.uuid, date: '2026-07-01', rating: 8, note: 'x',
      updated_at: '2026-07-01T09:00:00', deleted: false
    }];
    const merged = mergeMoodEntries(await allEntries(), stalePeer);
    expect(merged[0].deleted).toBe(true);   // the tombstone is newer and holds
  });

  it('an edit made elsewhere AFTER the delete brings the day back', async () => {
    await putEntry({ date: '2026-07-01', rating: 8, note: 'x' });
    const tomb = await deleteEntry('2026-07-01');

    const laterEdit = [{
      uuid: tomb.uuid, date: '2026-07-01', rating: 9, note: 'передумал',
      updated_at: '2099-01-01T00:00:00', deleted: false
    }];
    const merged = mergeMoodEntries(await allEntries(), laterEdit);
    expect(merged[0].deleted).toBe(false);
    expect(merged[0].note).toBe('передумал');
  });
});
