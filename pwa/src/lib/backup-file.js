// Full-fidelity backup / transfer file — a plaintext SNAPSHOT (the same
// shape the sync engine exchanges), so nothing is lost in translation and
// import follows the same additive+LWW merge rules as cloud sync.
//
// Two jobs:
//   * offline backup when no cloud is configured (complements the
//     human-readable Markdown export — this one restores losslessly);
//   * browser → installed-PWA transfer. On Android/Chrome both share one
//     origin storage, nothing to do; on iOS a Home-Screen app gets a
//     SEPARATE container from Safari, so the file is the bridge.

import { allEntries, putEntries } from './db.js';
import { getDeviceId, getDeviceName } from './vault.js';
import { buildSnapshot, mergeMoodEntries, validMood } from './snapshot.js';
import { todayISO } from './mood.js';

export async function exportBackup() {
  const snapshot = buildSnapshot(await allEntries(), getDeviceId(), getDeviceName());
  const filename = `index-life-backup-${todayISO()}.json`;
  const blob = new Blob([JSON.stringify(snapshot, null, 2)],
    { type: 'application/json' });

  // Same share-sheet-first pattern as the Markdown export.
  const file = new File([blob], filename, { type: 'application/json' });
  if (navigator.canShare?.({ files: [file] })) {
    try {
      await navigator.share({ files: [file], title: 'index.life backup' });
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

// Merge a backup file's entries into the local diary. Returns
// {added, total} of live entries. Throws a human message on junk input.
export async function importBackupText(text) {
  let obj;
  try {
    obj = JSON.parse(text);
  } catch {
    throw new Error('Файл не похож на резервную копию index.life');
  }
  const incoming = Array.isArray(obj?.mood_entries)
    ? obj.mood_entries.filter(validMood)
    : null;
  if (!incoming || !incoming.length) {
    throw new Error('В файле нет записей дневника');
  }
  const local = await allEntries();
  const liveBefore = local.filter((e) => !e.deleted).length;
  const merged = mergeMoodEntries(local, incoming);
  await putEntries(merged);
  const liveAfter = merged.filter((e) => !e.deleted).length;
  return { added: liveAfter - liveBefore, total: liveAfter };
}
