// App-level sync orchestrator — the glue that connects the persistent layers
// (IndexedDB entries, the localStorage vault) to the pure sync engine. The UI
// calls syncWith(transport) with a configured cloud transport (Google Drive,
// …); the engine and crypto do the rest.

import { allEntries, putEntries } from './db.js';
import { getDeviceId, getVaultKey, isEncryptionEnabled } from './vault.js';
import { fullSync } from './sync.js';

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
  const merged = await fullSync(transport, deviceId, local, vk, stats);
  await putEntries(merged);

  // locked/errors — peers whose data could NOT be read (key mismatch /
  // junk blob); the UI surfaces them so a broken link never looks "ok".
  return { entries: merged.length, locked: stats.locked, errors: stats.errors };
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
    out.push({ id, at, encrypted: env, self: id === ownDeviceId });
  }
  // self first, then most recently synced
  out.sort((a, b) => (a.self === b.self ? (b.at || 0) - (a.at || 0) : (a.self ? -1 : 1)));
  return out;
}
