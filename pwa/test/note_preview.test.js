// Notes are written on the desktop in a Markdown editor; the feed showed the
// raw source, so a reader got `## Заголовок`, `**жирный**` and `- пункт` as
// literal syntax. The preview strips the markup — the row is a two-line
// clamp, where a heading or a list cannot look like anything useful anyway.

import { describe, it, expect } from 'vitest';
import { notePreview } from '../src/lib/markdown.js';

describe('notePreview', () => {
  it('drops heading markers', () => {
    expect(notePreview('## Хороший день\n\nГулял в парке.'))
      .toBe('Хороший день Гулял в парке.');
  });

  it('unwraps bold, italic and strikethrough', () => {
    expect(notePreview('Было **важно** и *приятно*, но ~~устал~~'))
      .toBe('Было важно и приятно, но устал');
  });

  it('keeps a lone asterisk and mid-word underscores alone', () => {
    expect(notePreview('5 * 3 = 15, файл some_long_name.txt'))
      .toBe('5 * 3 = 15, файл some_long_name.txt');
  });

  it('flattens lists into readable text', () => {
    expect(notePreview('Дела:\n- купил хлеб\n- позвонил маме\n1. записал день'))
      .toBe('Дела: купил хлеб позвонил маме записал день');
  });

  it('keeps link text and drops the address', () => {
    expect(notePreview('Читал [статью про сон](https://example.com/sleep) вечером'))
      .toBe('Читал статью про сон вечером');
  });

  it('drops quote markers, rules and code fences', () => {
    expect(notePreview('> цитата\n\n---\n\n```\nкод\n```\n\nпотом'))
      .toBe('цитата потом');
  });

  it('unwraps inline code', () => {
    expect(notePreview('Починил `sync.js` наконец')).toBe('Починил sync.js наконец');
  });

  it('collapses blank lines', () => {
    expect(notePreview('первый\n\n\nвторой')).toBe('первый второй');
  });

  it('truncates a long note on a word boundary-ish and marks it', () => {
    const long = 'слово '.repeat(100);
    const out = notePreview(long, 40);
    expect(out.length).toBeLessThanOrEqual(41);
    expect(out.endsWith('…')).toBe(true);
  });

  it('handles empty input', () => {
    expect(notePreview('')).toBe('');
    expect(notePreview(null)).toBe('');
    expect(notePreview(undefined)).toBe('');
  });

  it('leaves a plain note untouched', () => {
    expect(notePreview('Просто хороший день, ничего особенного.'))
      .toBe('Просто хороший день, ничего особенного.');
  });
});

import { softenHardBreaks } from '../src/lib/markdown.js';

describe('line breaks written by the desktop editor', () => {
  it('drops the backslash where a plain newline means the same', () => {
    expect(softenHardBreaks('Абзац один.\\\nСтрока два.')).toBe('Абзац один.\nСтрока два.');
    expect(softenHardBreaks('> Цитата\\\n> вторая')).toBe('> Цитата\n> вторая');
    expect(softenHardBreaks('- пункт\\\n  продолжение')).toBe('- пункт\n  продолжение');
  });

  it('keeps it where the next line would start a block of its own', () => {
    for (const next of ['- не список', '# не заголовок', '1. не пункт', '---', '> не цитата']) {
      expect(softenHardBreaks(`Текст\\\n${next}`)).toBe(`Текст\\\n${next}`);
    }
  });

  it('leaves code fences and escaped backslashes alone', () => {
    expect(softenHardBreaks('```\nкод\\\nещё\n```')).toBe('```\nкод\\\nещё\n```');
    expect(softenHardBreaks('путь C:\\\\\nдальше')).toBe('путь C:\\\\\nдальше');
  });

  it('never shows a stray backslash in the feed', () => {
    expect(notePreview('Абзац\\\n- строка\\\nещё')).toBe('Абзац строка ещё');
  });
});
