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
  const merged = await fullSync(transport, deviceId, local, vk);
  await putEntries(merged);

  return { entries: merged.length };
}
