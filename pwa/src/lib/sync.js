// The sync engine — provider-agnostic, pure over entry arrays + a transport.
// Mirrors the desktop app/sync.py pull/push, so the phone and the desktop
// converge through one shared cloud folder. Encryption is mandatory for the
// PWA's cloud sync: the Vault Key (vk) is passed in by the caller (the vault
// state layer); the engine never sees a passphrase and never writes plaintext.

import * as crypto from './crypto.js';
import { buildSnapshot, mergeMoodEntries } from './snapshot.js';

export const VAULT_FILENAME = 'vault.json';
export const ownBlobName = (deviceId) => `device_${deviceId}.json`;

// True for an encrypted snapshot blob (vs a legacy plaintext desktop snapshot).
export function isEnvelope(obj) {
  return !!obj && typeof obj === 'object' && 'ct' in obj && 'alg' in obj && 'env' in obj;
}

// Read & merge every peer blob into `localEntries`; returns the merged array
// (the caller persists it). Dual-read: decrypts envelopes, still reads legacy
// plaintext desktop snapshots (migration), skips vault.json and our own blob.
// A null vk (locked) means encrypted peers are skipped — nothing leaks, sync
// simply doesn't progress.
//
// `stats`, when given, collects what could NOT be read: `locked` counts
// envelopes this key can't open (locked vault or key mismatch — the
// actionable case), `errors` counts unparseable blobs. A skipped peer means
// that device's changes silently stop arriving, so the UI must be able to
// say so instead of reporting a clean sync.
export async function pullPeers(transport, ownDeviceId, localEntries, vk, stats = null) {
  await crypto.ready;
  let entries = localEntries;
  for (const name of await transport.list()) {
    if (name === VAULT_FILENAME) continue;
    const text = await transport.get(name);
    if (text == null) continue;

    let obj;
    try {
      obj = JSON.parse(text);
    } catch {
      if (stats) stats.errors++;
      continue;
    }

    let snapshot;
    if (isEnvelope(obj)) {
      if (obj.device === ownDeviceId) continue; // our own encrypted blob
      if (!vk) {
        if (stats) stats.locked++;
        continue; // locked — can't read peers
      }
      try {
        snapshot = crypto.openEnvelope(text, vk);
      } catch {
        if (stats) stats.locked++;
        continue; // wrong key / tampered — skip, never fatal
      }
    } else {
      snapshot = obj;
      if (snapshot && snapshot.device_id === ownDeviceId) continue;
    }

    if (snapshot && Array.isArray(snapshot.mood_entries)) {
      // `losers` collects local versions this merge replaces, so the app can
      // show the user what was overwritten instead of losing it silently.
      entries = mergeMoodEntries(entries, snapshot.mood_entries,
                                 stats ? (stats.losers || (stats.losers = [])) : null);
      // Collect peers' display names for the devices panel (the caller
      // caches them — envelope headers stay name-free, so a peer's name is
      // only known after a successful decrypt+merge).
      if (stats && snapshot.device_id && typeof snapshot.device_name === 'string') {
        (stats.names || (stats.names = {}))[snapshot.device_id] =
          snapshot.device_name.slice(0, 60);
      }
    }
  }
  return entries;
}

// Seal our snapshot and write it. Requires a vk — refuses (throws) rather than
// ever putting plaintext in the cloud.
export async function pushSnapshot(transport, ownDeviceId, entries, vk, deviceName = null) {
  await crypto.ready;
  if (!vk) throw new Error('vault is locked — refusing to push plaintext');
  const snapshot = buildSnapshot(entries, ownDeviceId, deviceName);
  const text = crypto.sealEnvelope(snapshot, vk, {
    device: ownDeviceId,
    snapshotVersion: snapshot.snapshot_version,
    writtenAt: snapshot.generated_at
  });
  await transport.put(ownBlobName(ownDeviceId), text);
}

// One cycle: pull peers → merge → push our merged state. Returns the merged
// entries for the caller to persist locally. `stats` — see pullPeers.
export async function fullSync(transport, ownDeviceId, localEntries, vk,
                               stats = null, deviceName = null) {
  const merged = await pullPeers(transport, ownDeviceId, localEntries, vk, stats);
  await pushSnapshot(transport, ownDeviceId, merged, vk, deviceName);
  return merged;
}
