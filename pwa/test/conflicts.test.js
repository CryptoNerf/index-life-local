// A losing edit must be recoverable, not gone.
//
// Merging is last-write-wins by date, so an edit made here can be replaced by
// one made on the desktop — for reasons as mundane as a phone clock a couple
// of minutes behind. The desktop has always kept the loser in a 30-day log;
// the phone used to drop it, which is the worst thing a diary can do.

import { describe, it, expect, beforeEach } from 'vitest';
import { mergeMoodEntries } from '../src/lib/snapshot.js';
import {
  recordConflicts, listConflicts, unseenCount, markSeen,
  forgetConflict, clearConflicts
} from '../src/lib/conflicts.js';

function lsShim() {
  const m = new Map();
  return {
    getItem: (k) => (m.has(k) ? m.get(k) : null),
    setItem: (k, v) => m.set(k, String(v)),
    removeItem: (k) => m.delete(k)
  };
}

beforeEach(() => {
  globalThis.localStorage = lsShim();
});

const local = (over = {}) => ({
  uuid: 'u1', date: '2026-07-01', rating: 8, note: 'моя версия',
  updated_at: '2026-07-01T12:00:00.000Z', deleted: false, ...over
});
const peer = (over = {}) => ({
  uuid: 'u1', date: '2026-07-01', rating: 4, note: 'версия с компьютера',
  updated_at: '2026-07-01T12:05:00', deleted: false, device_id: 'dev-desktop', ...over
});

describe('the merge reports what it replaced', () => {
  it('collects the local version a newer peer overwrote', () => {
    const losers = [];
    const merged = mergeMoodEntries([local()], [peer()], losers);

    expect(merged[0].note).toBe('версия с компьютера'); // peer still wins
    expect(losers).toHaveLength(1);
    expect(losers[0]).toMatchObject({
      date: '2026-07-01', rating: 8, note: 'моя версия', peerDevice: 'dev-desktop'
    });
  });

  it('says nothing when the content is identical', () => {
    const losers = [];
    mergeMoodEntries([local()], [peer({ rating: 8, note: 'моя версия' })], losers);
    expect(losers).toHaveLength(0);
  });

  it('says nothing when the local row lost as a tie or was older-wins', () => {
    const losers = [];
    // peer is older → local keeps, nothing replaced
    mergeMoodEntries([local()], [peer({ updated_at: '2026-07-01T11:00:00' })], losers);
    expect(losers).toHaveLength(0);
  });

  it('does not count a tombstone being resurrected as a loss', () => {
    const losers = [];
    mergeMoodEntries([local({ deleted: true })], [peer()], losers);
    expect(losers).toHaveLength(0);
  });

  it('records an incoming deletion of live local content', () => {
    const losers = [];
    mergeMoodEntries([local()], [peer({ deleted: true, note: null, rating: 8 })], losers);
    expect(losers).toHaveLength(1);
    expect(losers[0].note).toBe('моя версия'); // the text is still recoverable
  });

  it('stays backward compatible when no collector is passed', () => {
    expect(() => mergeMoodEntries([local()], [peer()])).not.toThrow();
  });

  it('catches the phone-clock-behind case', () => {
    // Phone wrote at 12:04 by its own clock, which runs 2 min slow; the
    // desktop wrote at 12:05 real time. The desktop wins and the phone user's
    // newer text would vanish — this is the case the log exists for.
    const losers = [];
    const merged = mergeMoodEntries(
      [local({ note: 'написано на телефоне', updated_at: '2026-07-01T12:03:00.000Z' })],
      [peer({ note: 'с компьютера', updated_at: '2026-07-01T12:05:00' })],
      losers
    );
    expect(merged[0].note).toBe('с компьютера');
    expect(losers[0].note).toBe('написано на телефоне');
  });
});

describe('the log', () => {
  it('keeps rows, newest first, and counts unseen ones', () => {
    const T = Date.now();
    recordConflicts([{ date: '2026-07-01', rating: 8, note: 'a' }], T - 2000);
    recordConflicts([{ date: '2026-07-02', rating: 5, note: 'b' }], T - 1000);

    const rows = listConflicts();
    expect(rows.map((r) => r.date)).toEqual(['2026-07-02', '2026-07-01']);
    expect(unseenCount()).toBe(2);

    markSeen();
    expect(unseenCount()).toBe(0);
  });

  it('forgets a single row once it has been restored', () => {
    const T = Date.now();
    recordConflicts([{ date: '2026-07-01', rating: 8, note: 'a' }], T - 2000);
    recordConflicts([{ date: '2026-07-02', rating: 5, note: 'b' }], T - 1000);

    forgetConflict(T - 2000, '2026-07-01');
    expect(listConflicts().map((r) => r.date)).toEqual(['2026-07-02']);
  });

  it('drops rows older than 30 days', () => {
    const now = Date.now();
    recordConflicts([{ date: '2026-01-01', rating: 3, note: 'old' }], now - 31 * 864e5);
    recordConflicts([{ date: '2026-07-01', rating: 8, note: 'fresh' }], now);
    expect(listConflicts().map((r) => r.note)).toEqual(['fresh']);
  });

  it('records nothing for an empty merge', () => {
    expect(recordConflicts([])).toBe(0);
    expect(recordConflicts(null)).toBe(0);
    expect(listConflicts()).toEqual([]);
  });

  it('survives junk in storage', () => {
    localStorage.setItem('indexlife:conflicts', 'not json');
    expect(listConflicts()).toEqual([]);
    expect(() => recordConflicts([{ date: '2026-07-01', rating: 1, note: 'x' }])).not.toThrow();
  });

  it('clearConflicts empties the log', () => {
    recordConflicts([{ date: '2026-07-01', rating: 8, note: 'a' }]);
    clearConflicts();
    expect(listConflicts()).toEqual([]);
  });
});
