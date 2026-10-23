// Markdown export — the always-available, app-independent escape hatch.
// A human-readable copy the user can keep anywhere, so data is never locked
// into the app or any single storage.

import { allEntries } from './db.js';
import { todayISO, prettyDate } from './mood.js';

export function buildMarkdown(entries) {
  const rows = entries
    .filter((e) => !e.deleted)
    .sort((a, b) => b.date.localeCompare(a.date));

  let md = '# index.life — дневник настроения\n\n';
  md += `_Экспортировано ${prettyDate(todayISO())} · записей: ${rows.length}_\n\n`;
  for (const e of rows) {
    md += `## ${prettyDate(e.date)} — ${e.rating}/10\n\n`;
    if (e.note && e.note.trim()) md += `${e.note.trim()}\n\n`;
  }
  return md;
}

export async function exportMarkdown() {
  const md = buildMarkdown(await allEntries());
  const filename = `index-life-${todayISO()}.md`;
  const blob = new Blob([md], { type: 'text/markdown;charset=utf-8' });

  // Prefer the native share sheet on phones (lets the user save to Files,
  // send to themselves, etc.); fall back to a direct download elsewhere.
  const file = new File([blob], filename, { type: 'text/markdown' });
  if (navigator.canShare?.({ files: [file] })) {
    try {
      await navigator.share({ files: [file], title: 'index.life' });
      return;
    } catch (err) {
      if (err?.name === 'AbortError') return; // user cancelled — not an error
    }
  }
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

// ── Feed preview ─────────────────────────────────────────────────────
// Notes are written on the desktop in a Markdown editor, and the feed shows
// the first couple of lines of one. Printing the source put `## Заголовок`,
// `**жирный**` and `- пункт` in front of the reader as literal syntax.
//
// The preview STRIPS the markup rather than rendering it: the row is a
// two-line clamp, where a heading or a list cannot look like anything useful
// anyway. Editing still shows the real source, which is what you edit.
export function notePreview(note, limit = 240) {
  if (!note) return '';
  let text = String(note);

  text = text
    .replace(/(?<!\\)\\\n/g, '\n')            // hard line breaks
    .replace(/```[\s\S]*?```/g, ' ')             // fenced code blocks
    .replace(/^\s{0,3}(?:[-*_]\s*){3,}$/gm, ' ')  // horizontal rules
    .replace(/^\s{0,3}#{1,6}\s+/gm, '')          // heading markers
    .replace(/^\s{0,3}>\s?/gm, '')               // quote markers
    .replace(/^\s{0,3}(?:[-*+]|\d+[.)])\s+/gm, '') // list markers
    .replace(/!\[([^\]]*)\]\([^)]*\)/g, '$1')     // images → alt text
    .replace(/\[([^\]]+)\]\([^)]*\)/g, '$1')      // links → their text
    .replace(/(\*\*|__)(.*?)\1/g, '$2')          // bold
    .replace(/(^|\W)([*_])(?=\S)(.*?\S)\2/g, '$1$3') // italic, not mid-word
    .replace(/~~(.*?)~~/g, '$1')                 // strikethrough
    .replace(/`([^`]*)`/g, '$1')                 // inline code
    .replace(/\s+/g, ' ')
    .trim();

  return text.length > limit ? text.slice(0, limit).trimEnd() + '…' : text;
}

// ── Line breaks inside a paragraph ───────────────────────────────────
// The desktop editor writes a line break inside a paragraph as Markdown's
// "backslash, newline". Notes are read with single newlines as breaks, so the
// backslash only matters where the next line would otherwise start a block of
// its own (a heading, a list item, a quote, a rule, a fence). Everywhere else
// it showed up here as a stray "\" at the end of a line. Same rule as the
// desktop's app/note_text.py soften_hard_breaks.
const BLOCK_START = /^\s{0,3}(?:#{1,6}(?:\s|$)|>|[*+-](?:\s|$)|\d{1,9}[.)](?:\s|$)|```|~~~|[-=]+\s*$|\*{3,}\s*$|_{3,}\s*$)/;
const QUOTE_PREFIX = /^(?:\s{0,3}>\s?)+/;

export function softenHardBreaks(markdown) {
  if (!markdown || !markdown.includes('\\\n')) return markdown || '';
  const lines = markdown.split('\n');
  let inFence = false;
  return lines.map((line, i) => {
    if (/^\s*(```|~~~)/.test(line)) inFence = !inFence;
    const trailing = line.length - line.replace(/\\+$/, '').length;
    if (inFence || trailing % 2 !== 1 || i + 1 >= lines.length) return line;
    const next = lines[i + 1];
    const prefix = (line.match(QUOTE_PREFIX) || [''])[0];
    let rest = next;
    if (prefix) {
      const np = next.match(QUOTE_PREFIX);
      if (np && np[0].split('>').length === prefix.split('>').length) rest = next.slice(np[0].length);
    }
    return rest.trim() && !BLOCK_START.test(rest) ? line.slice(0, -1) : line;
  }).join('\n');
}
