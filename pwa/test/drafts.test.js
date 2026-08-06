// draftIsFresh — the "which wins on the capture screen" rule. A draft keeps
// unsaved typing safe, but a stale draft must not hide (and, on Save,
// overwrite) an entry that was edited on another device and synced later.

import { describe, it, expect } from 'vitest';
import { draftIsFresh } from '../src/lib/drafts.js';

const entryAt = (iso) => ({ rating: 5, note: 'synced', updated_at: iso });

describe('draftIsFresh', () => {
  it('no draft → entry wins', () => {
    expect(draftIsFresh(null, entryAt('2026-07-01T10:00:00.000Z'))).toBe(false);
  });

  it('draft with no saved entry → draft wins', () => {
    expect(draftIsFresh({ rating: 3, note: 'typing', at: 1 }, null)).toBe(true);
  });

  it('draft newer than the synced entry → draft wins', () => {
    const draft = { rating: 3, note: 'typing', at: Date.parse('2026-07-01T12:00:00Z') };
    expect(draftIsFresh(draft, entryAt('2026-07-01T10:00:00.000Z'))).toBe(true);
  });

  it('entry synced after the draft was written → entry wins', () => {
    const draft = { rating: 3, note: 'stale typing', at: Date.parse('2026-07-01T10:00:00Z') };
    expect(draftIsFresh(draft, entryAt('2026-07-01T12:00:00.000Z'))).toBe(false);
  });

  it('handles desktop-style zone-less timestamps as UTC', () => {
    const draft = { rating: 3, note: 'typing', at: Date.parse('2026-07-01T11:00:00Z') };
    expect(draftIsFresh(draft, entryAt('2026-07-01T10:00:00.500000'))).toBe(true);
    expect(draftIsFresh(draft, entryAt('2026-07-01T12:00:00.500000'))).toBe(false);
  });

  it('pre-`at` drafts (age unknown) lose to any timestamped entry', () => {
    const legacyDraft = { rating: 3, note: 'old draft' };
    expect(draftIsFresh(legacyDraft, entryAt('2026-07-01T10:00:00.000Z'))).toBe(false);
  });

  it('an entry without a parseable updated_at never beats a draft', () => {
    const draft = { rating: 3, note: 'typing', at: 1 };
    expect(draftIsFresh(draft, { rating: 5, note: 'x', updated_at: null })).toBe(true);
  });
});

// ── What the editor shows for a day ─────────────────────────────────
// A tombstone keeps its old text so the deletion can travel to peers that
// still hold the entry. Feeding that text to the editor showed content the
// user had deliberately deleted on another device — and saving pushed it
// back, resurrecting the entry.

import { editorStateFor } from '../src/lib/drafts.js';

describe('editorStateFor', () => {
  const entry = (over = {}) => ({
    date: '2026-07-01', rating: 7, note: 'текст записи',
    updated_at: '2026-07-01T10:00:00.000Z', deleted: false, ...over
  });

  it('shows a live entry', () => {
    expect(editorStateFor(entry(), null)).toEqual({
      rating: 7, note: 'текст записи', deletedElsewhere: false
    });
  });

  it('shows an empty form for a day deleted on another device', () => {
    expect(editorStateFor(entry({ deleted: true }), null)).toEqual({
      rating: 0, note: '', deletedElsewhere: true
    });
  });

  it('keeps an unsaved draft even when the day was deleted elsewhere', () => {
    const draft = { rating: 5, note: 'пишу прямо сейчас', at: Date.parse('2026-07-02T10:00:00Z') };
    expect(editorStateFor(entry({ deleted: true }), draft)).toEqual({
      rating: 5, note: 'пишу прямо сейчас', deletedElsewhere: false
    });
  });

  it('ignores a stale draft', () => {
    const stale = { rating: 2, note: 'старый черновик', at: Date.parse('2026-06-01T10:00:00Z') };
    expect(editorStateFor(entry(), stale)).toEqual({
      rating: 7, note: 'текст записи', deletedElsewhere: false
    });
  });

  it('shows an empty form for a day with nothing at all', () => {
    expect(editorStateFor(null, null)).toEqual({
      rating: 0, note: '', deletedElsewhere: false
    });
  });
});
