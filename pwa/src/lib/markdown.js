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
