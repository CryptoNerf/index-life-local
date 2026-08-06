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
// `seen` maps blob name -> the change tag last merged from it. A blob whose
// tag is unchanged is skipped without downloading — the difference between a
// few kilobytes of listing and re-downloading every peer's whole diary on
// every cycle, which on a phone is real mobile data and real battery.
// Freshly merged tags are reported back through `stats.tags`; the caller
// commits them only after the merged result is safely stored, so a failed
// save can never make us skip a peer we haven't actually taken in.
export async function pullPeers(transport, ownDeviceId, localEntries, vk,
                                stats = null, seen = null) {
  await crypto.ready;
  let entries = localEntries;

  let listing;
  if (typeof transport.listMeta === 'function') {
    listing = await transport.listMeta();
  } else {
    listing = (await transport.list()).map((name) => ({ name, tag: null }));
  }

  const ownBlob = ownBlobName(ownDeviceId);
  for (const { name, tag } of listing) {
    if (name === VAULT_FILENAME) continue;
    // Our own snapshot, recognised by name before spending a download on it.
    // The device_id checks further down stay as a safety net for blobs under
    // an unexpected name.
    if (name === ownBlob) continue;
    if (seen && tag != null && seen[name] === tag) {
      if (stats) stats.skipped = (stats.skipped || 0) + 1;
      continue;                       // unchanged since we last merged it
    }
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
      if (stats && tag != null) (stats.tags || (stats.tags = {}))[name] = tag;
    }
  }
  return entries;
}

// A stable fingerprint of what we would publish, ignoring the timestamp that
// changes on every build. Mirrors the desktop's _snapshot_content_hash: it is
// what lets an idle app stop re-uploading the same diary every few minutes.
export function snapshotContentHash(snapshot) {
  const { generated_at, ...rest } = snapshot;
  return crypto.canonicalString(rest);
}

// Seal our snapshot and write it. Requires a vk — refuses (throws) rather than
// ever putting plaintext in the cloud. Returns the content hash of what was
// published, or null when the push was skipped as unchanged.
export async function pushSnapshot(transport, ownDeviceId, entries, vk,
                                   deviceName = null, lastHash = null) {
  await crypto.ready;
  if (!vk) throw new Error('vault is locked — refusing to push plaintext');
  const snapshot = buildSnapshot(entries, ownDeviceId, deviceName);
  const hash = snapshotContentHash(snapshot);
  if (lastHash != null && hash === lastHash) return null;   // nothing new to say
  const text = crypto.sealEnvelope(snapshot, vk, {
    device: ownDeviceId,
    snapshotVersion: snapshot.snapshot_version,
    writtenAt: snapshot.generated_at
  });
  await transport.put(ownBlobName(ownDeviceId), text);
  return hash;
}

// One cycle: pull peers → merge → push our merged state. Returns the merged
// entries for the caller to persist locally. `stats` — see pullPeers.
// `seen`/`lastHash` carry the previous cycle's change marks (see pullPeers);
// the new marks come back in `stats.tags` / `stats.pushHash`.
export async function fullSync(transport, ownDeviceId, localEntries, vk,
                               stats = null, deviceName = null,
                               { seen = null, lastHash = null } = {}) {
  const merged = await pullPeers(transport, ownDeviceId, localEntries, vk, stats, seen);
  const hash = await pushSnapshot(transport, ownDeviceId, merged, vk, deviceName, lastHash);
  if (stats) stats.pushHash = hash;      // null when the push was skipped
  return merged;
}
