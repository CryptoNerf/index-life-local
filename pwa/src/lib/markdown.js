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
