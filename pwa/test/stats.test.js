// currentStreak — the Capture screen's daily-habit counter — and the
// Russian plural helper it is rendered with.

import { describe, it, expect } from 'vitest';
import { currentStreak } from '../src/lib/stats.js';
import { pluralDays } from '../src/lib/mood.js';

const e = (date, over = {}) => ({ date, rating: 7, deleted: false, ...over });

describe('currentStreak', () => {
  it('empty diary → 0', () => {
    expect(currentStreak([], '2026-07-04')).toBe(0);
  });

  it('counts consecutive days ending today', () => {
    const entries = [e('2026-07-02'), e('2026-07-03'), e('2026-07-04')];
    expect(currentStreak(entries, '2026-07-04')).toBe(3);
  });

  it("today not yet logged → the streak isn't broken, counts from yesterday", () => {
    const entries = [e('2026-07-02'), e('2026-07-03')];
    expect(currentStreak(entries, '2026-07-04')).toBe(2);
  });

  it('a gap resets the streak', () => {
    const entries = [e('2026-07-01'), e('2026-07-03'), e('2026-07-04')];
    expect(currentStreak(entries, '2026-07-04')).toBe(2);
  });

  it('two-day-old last entry → streak over', () => {
    expect(currentStreak([e('2026-07-01')], '2026-07-04')).toBe(0);
  });

  it('ignores tombstones and unrated days', () => {
    const entries = [
      e('2026-07-03', { deleted: true }),
      e('2026-07-04', { rating: 0 }),
    ];
    expect(currentStreak(entries, '2026-07-04')).toBe(0);
  });

  it('crosses month boundaries', () => {
    const entries = [e('2026-06-29'), e('2026-06-30'), e('2026-07-01')];
    expect(currentStreak(entries, '2026-07-01')).toBe(3);
  });
});

describe('pluralDays', () => {
  it.each([
    [1, 'день'], [2, 'дня'], [4, 'дня'], [5, 'дней'],
    [11, 'дней'], [12, 'дней'], [14, 'дней'],
    [21, 'день'], [22, 'дня'], [25, 'дней'],
    [101, 'день'], [111, 'дней'],
  ])('%i → %s', (n, word) => {
    expect(pluralDays(n)).toBe(word);
  });
});
