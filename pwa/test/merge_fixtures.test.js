// Shared merge conformance (JS side). The PWA's mergeMoodEntries must
// reproduce docs/sync-spec/fixtures/merge/expected.json — the exact same
// fixture the Python desktop test asserts against. Phone and desktop converge
// identically or this fails.

import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { mergeMoodEntries, toEpochMs } from '../src/lib/snapshot.js';

const FX = new URL('../../docs/sync-spec/fixtures/merge/', import.meta.url);
const FX_TS = new URL('../../docs/sync-spec/fixtures/merge-timestamps/', import.meta.url);
const load = (n, base = FX) => JSON.parse(readFileSync(new URL(n, base), 'utf8'));
const byDate = (arr) => [...arr].sort((x, y) => x.date.localeCompare(y.date));

describe('shared merge fixtures', () => {
  const a = load('a.json');
  const b = load('b.json');
  const expected = load('expected.json');

  it('mergeMoodEntries(a, b) reproduces expected.json', () => {
    const got = mergeMoodEntries(a.mood_entries, b.mood_entries);
    expect(byDate(got)).toEqual(byDate(expected.mood_entries));
  });

  it('is idempotent — re-merging b changes nothing', () => {
    const once = mergeMoodEntries(a.mood_entries, b.mood_entries);
    const twice = mergeMoodEntries(once, b.mood_entries);
    expect(byDate(twice)).toEqual(byDate(once));
  });
});

// ── mixed timestamp styles (desktop naive UTC vs PWA Z-suffixed) ─────
// fixtures/merge-timestamps/: `a` is a desktop-style snapshot (naive-UTC
// strings), `b` a phone-style one (Z-suffixed ms). SPEC §Timestamps: both
// spellings of an instant must compare equal. The JS merge keeps whichever
// raw string won, so timestamps are compared as instants (toEpochMs); all
// other fields must match expected.json exactly.

const asInstants = (e) => ({
  ...e,
  created_at: toEpochMs(e.created_at),
  updated_at: toEpochMs(e.updated_at)
});

describe('shared merge-timestamps fixtures', () => {
  const a = load('a.json', FX_TS);
  const b = load('b.json', FX_TS);
  const expected = load('expected.json', FX_TS);

  it('merging desktop-style base with phone-style peer reproduces expected.json', () => {
    const got = mergeMoodEntries(a.mood_entries, b.mood_entries);
    expect(byDate(got).map(asInstants)).toEqual(byDate(expected.mood_entries).map(asInstants));
  });

  it('is idempotent — re-merging the phone snapshot changes nothing', () => {
    const once = mergeMoodEntries(a.mood_entries, b.mood_entries);
    const twice = mergeMoodEntries(once, b.mood_entries);
    expect(byDate(twice).map(asInstants)).toEqual(byDate(once).map(asInstants));
  });
});
