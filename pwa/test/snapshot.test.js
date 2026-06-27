// Snapshot conformance: (1) a built snapshot validates against the SHARED
// schema both stacks use (docs/sync-spec/snapshot.schema.json); (2) the JS
// merge obeys the same additive + LWW + tombstone rules as the desktop.

import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import Ajv2020 from 'ajv/dist/2020.js';
import { buildSnapshot, mergeMoodEntries, applySnapshot } from '../src/lib/snapshot.js';

const SPEC = new URL('../../docs/sync-spec/', import.meta.url);
const schema = JSON.parse(readFileSync(new URL('snapshot.schema.json', SPEC), 'utf8'));
const sample = JSON.parse(readFileSync(new URL('fixtures/snapshot.sample.json', SPEC), 'utf8'));

const ajv = new Ajv2020({ strict: false });
const validate = ajv.compile(schema);

const OLD = '2025-01-01T12:00:00';
const NEW = '2025-02-01T12:00:00';
const entry = (date, over = {}) => ({
  uuid: `u-${date}`, date, rating: 5, note: 'x',
  created_at: OLD, updated_at: OLD, device_id: 'dev-a', deleted: false, ...over
});

// ── schema conformance ───────────────────────────────────────

describe('built snapshot matches the shared schema', () => {
  it('validates a normal snapshot', () => {
    const snap = buildSnapshot([entry('2026-06-20'), entry('2026-06-19', { deleted: true })], 'dev-a');
    expect(validate(snap)).toBe(true);
  });

  it('validates an empty snapshot', () => {
    expect(validate(buildSnapshot([], 'dev-a'))).toBe(true);
  });

  it('the committed sample fixture validates (same file the Python test uses)', () => {
    expect(validate(sample)).toBe(true);
  });
});

// ── merge rules (mirror test_sync_merge.py mood cases) ────────

describe('mergeMoodEntries', () => {
  it('inserts a day the peer has and we do not', () => {
    const out = mergeMoodEntries([], [entry('2026-06-20')]);
    expect(out).toHaveLength(1);
    expect(out[0].date).toBe('2026-06-20');
  });

  it('a strictly newer peer overwrites local', () => {
    const out = mergeMoodEntries(
      [entry('2026-06-20', { rating: 3, updated_at: OLD })],
      [entry('2026-06-20', { rating: 9, updated_at: NEW })]
    );
    expect(out[0].rating).toBe(9);
  });

  it('an older peer is ignored', () => {
    const out = mergeMoodEntries(
      [entry('2026-06-20', { rating: 3, updated_at: NEW })],
      [entry('2026-06-20', { rating: 9, updated_at: OLD })]
    );
    expect(out[0].rating).toBe(3);
  });

  it('equal timestamps keep local', () => {
    const out = mergeMoodEntries(
      [entry('2026-06-20', { rating: 3, updated_at: NEW })],
      [entry('2026-06-20', { rating: 9, updated_at: NEW })]
    );
    expect(out[0].rating).toBe(3);
  });

  it('a newer remote tombstone deletes the local entry', () => {
    const out = mergeMoodEntries(
      [entry('2026-06-20', { updated_at: OLD })],
      [entry('2026-06-20', { deleted: true, updated_at: NEW })]
    );
    expect(out[0].deleted).toBe(true);
  });

  it('a peer simply missing a day does NOT delete it', () => {
    const out = mergeMoodEntries([entry('2026-06-20')], []);
    expect(out[0].deleted).toBe(false);
  });

  it('skips invalid rows (bad date / out-of-range rating)', () => {
    const out = mergeMoodEntries([], [
      { date: 'not-a-date', rating: 5, deleted: false },
      { date: '2026-06-20', rating: 99, deleted: false },
      entry('2026-06-21')
    ]);
    expect(out.map((e) => e.date)).toEqual(['2026-06-21']);
  });

  it('is idempotent — merging the same peer twice changes nothing', () => {
    const peer = [entry('2026-06-20', { rating: 9, updated_at: NEW })];
    const once = mergeMoodEntries([entry('2026-06-20', { updated_at: OLD })], peer);
    const twice = mergeMoodEntries(once, peer);
    expect(twice).toEqual(once);
  });

  it('does not mutate the inputs', () => {
    const local = [entry('2026-06-20', { rating: 3, updated_at: OLD })];
    mergeMoodEntries(local, [entry('2026-06-20', { rating: 9, updated_at: NEW })]);
    expect(local[0].rating).toBe(3);
  });
});

describe('applySnapshot', () => {
  it('never merges our own snapshot', () => {
    const own = buildSnapshot([entry('2026-06-20')], 'dev-a');
    expect(applySnapshot([], own, 'dev-a')).toEqual([]);
  });

  it('merges a peer snapshot', () => {
    const peer = buildSnapshot([entry('2026-06-20')], 'dev-b');
    const out = applySnapshot([], peer, 'dev-a');
    expect(out).toHaveLength(1);
  });
});
