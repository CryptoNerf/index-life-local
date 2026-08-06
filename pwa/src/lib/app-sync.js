// App-level sync orchestrator — the glue that connects the persistent layers
// (IndexedDB entries, the localStorage vault) to the pure sync engine. The UI
// calls syncWith(transport) with a configured cloud transport (Google Drive,
// …); the engine and crypto do the rest.

import { allEntries, putEntries } from './db.js';
import { getDeviceId, getDeviceName, getVaultKey, isEncryptionEnabled } from './vault.js';
import { fullSync } from './sync.js';
import { recordConflicts } from './conflicts.js';

// ── Change marks ─────────────────────────────────────────────────────
// What we already merged from each peer blob, and what we last published.
// Without them the phone re-downloaded every peer's whole diary and
// re-uploaded its own on every cycle — hundreds of kilobytes per sync, on
// mobile data, usually with nothing changed at all.
const SEEN_TAGS_KEY = 'indexlife:peer-tags';
const PUSH_HASH_KEY = 'indexlife:push-hash';

function loadSeenTags() {
  try {
    const raw = JSON.parse(localStorage.getItem(SEEN_TAGS_KEY) || '{}');
    return raw && typeof raw === 'object' ? raw : {};
  } catch {
    return {};
  }
}

function saveSeenTags(fresh) {
  if (!fresh) return;
  try {
    localStorage.setItem(SEEN_TAGS_KEY,
                         JSON.stringify({ ...loadSeenTags(), ...fresh }));
  } catch {
    /* best-effort: without the marks we just re-download next time */
  }
}

function loadPushHash() {
  try {
    return localStorage.getItem(PUSH_HASH_KEY);
  } catch {
    return null;
  }
}

function savePushHash(hash) {
  try {
    localStorage.setItem(PUSH_HASH_KEY, hash);
  } catch {
    /* best-effort */
  }
}

// Forget every change mark — used when the folder or the key changes and
// what we merged before says nothing about what is there now.
export function resetSyncMarks() {
  try {
    localStorage.removeItem(SEEN_TAGS_KEY);
    localStorage.removeItem(PUSH_HASH_KEY);
  } catch {
    /* best-effort */
  }
}

// Peers' display names, cached from their (decrypted) snapshots — envelope
// headers are name-free, so a peer's name is only learnable on merge.
const PEER_NAME_PREFIX = 'indexlife:peer-name:';

export function getPeerName(deviceId) {
  try {
    return localStorage.getItem(PEER_NAME_PREFIX + deviceId);
  } catch {
    return null;
  }
}

function cachePeerNames(names) {
  for (const [id, name] of Object.entries(names || {})) {
    try {
      localStorage.setItem(PEER_NAME_PREFIX + id, name);
    } catch {
      /* best-effort */
    }
  }
}

// One sync cycle against a transport: pull peers → merge → push our state →
// persist the merged result locally. Returns a small status object.
//
// Requires an unlocked vault (cloud sync is encrypted-only). Throws a tagged
// error the UI can map to "connect/unlock first" rather than a raw failure.
export async function syncWith(transport) {
  if (!isEncryptionEnabled()) {
    throw new Error('encryption-not-enabled');
  }
  const vk = getVaultKey();
  if (!vk) {
    throw new Error('vault-locked');
  }

  const deviceId = getDeviceId();
  const local = await allEntries();
  const stats = { locked: 0, errors: 0 };
  const merged = await fullSync(transport, deviceId, local, vk, stats,
                                getDeviceName(),
                                { seen: loadSeenTags(), lastHash: loadPushHash() });
  await putEntries(merged);
  cachePeerNames(stats.names);
  // Change marks are committed only now — after the merged result is stored.
  // Recording them earlier would let a failed save make the next cycle skip a
  // peer whose data we never actually kept.
  saveSeenTags(stats.tags);
  if (stats.pushHash) savePushHash(stats.pushHash);
  // Keep whatever this merge overwrote — a losing edit must be recoverable,
  // not gone (see lib/conflicts.js).
  const replaced = recordConflicts(stats.losers);

  // locked/errors — peers whose data could NOT be read (key mismatch /
  // junk blob); the UI surfaces them so a broken link never looks "ok".
  return {
    entries: merged.length, locked: stats.locked, errors: stats.errors,
    replaced, skipped: stats.skipped || 0
  };
}

// ── Devices panel ────────────────────────────────────────────────────
// Devices seen in the cloud folder — plaintext headers only (envelope
// routing header or a legacy snapshot's top fields), never decrypts, so
// it works even before the vault is unlocked. Answers "did my phone and
// the desktop actually meet?" — the question the setup flow left open.
import { isEnvelope } from './sync.js';
import { toEpochMs } from './snapshot.js';

export async function listDevices(transport, ownDeviceId = getDeviceId()) {
  const out = [];
  for (const name of await transport.list()) {
    if (!name.startsWith('device_') || !name.endsWith('.json')) continue;
    const text = await transport.get(name);
    if (text == null) continue;
    let obj;
    try {
      obj = JSON.parse(text);
    } catch {
      continue;
    }
    const env = isEnvelope(obj);
    const id = (env ? obj.device : obj.device_id) || '?';
    const at = toEpochMs(env ? obj.written_at : obj.generated_at);
    const self = id === ownDeviceId;
    // Display name: plaintext desktop snapshots carry it in the open;
    // encrypted peers' names come from the merge-time cache.
    const peerName = env ? getPeerName(id)
      : (typeof obj.device_name === 'string' ? obj.device_name : getPeerName(id));
    out.push({
      id, at, encrypted: env, self,
      name: self ? getDeviceName() : (peerName || null)
    });
  }
  // self first, then most recently synced
  out.sort((a, b) => (a.self === b.self ? (b.at || 0) - (a.at || 0) : (a.self ? -1 : 1)));
  return out;
}
