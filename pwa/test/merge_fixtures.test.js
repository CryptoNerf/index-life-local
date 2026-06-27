// Shared merge conformance (JS side). The PWA's mergeMoodEntries must
// reproduce docs/sync-spec/fixtures/merge/expected.json — the exact same
// fixture the Python desktop test asserts against. Phone and desktop converge
// identically or this fails.

import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { mergeMoodEntries } from '../src/lib/snapshot.js';

const FX = new URL('../../docs/sync-spec/fixtures/merge/', import.meta.url);
const load = (n) => JSON.parse(readFileSync(new URL(n, FX), 'utf8'));
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
