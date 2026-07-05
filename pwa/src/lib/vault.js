// PWA vault state — the device-local layer between crypto.js and the sync
// engine, mirroring the desktop app/sync_vault.py. The Vault Key and the
// enabled flag live in localStorage (device-local, never synced — like the
// desktop's sync_meta), so the key never leaves the phone. The encrypted
// cloud holds only ciphertext + the wrapped-key vault.json.

import * as crypto from './crypto.js';
import { VAULT_FILENAME, isEnvelope } from './sync.js';

const DEVICE_KEY = 'indexlife:device-id';
const ENABLED_KEY = 'indexlife:enc-enabled';
const VK_KEY = 'indexlife:vault-key'; // hex

// ── device identity ──────────────────────────────────────────────────
export function getDeviceId() {
  let id = localStorage.getItem(DEVICE_KEY);
  if (!id) {
    id = globalThis.crypto.randomUUID();
    localStorage.setItem(DEVICE_KEY, id);
  }
  return id;
}

// ── local state ──────────────────────────────────────────────────────
export function isEncryptionEnabled() {
  return localStorage.getItem(ENABLED_KEY) === 'true';
}

export function getVaultKey() {
  const hex = localStorage.getItem(VK_KEY);
  if (!hex) return null;
  try {
    const vk = crypto.fromHex(hex);
    return vk.length === crypto.VK_BYTES ? vk : null;
  } catch {
    return null;
  }
}

export function isUnlocked() {
  return isEncryptionEnabled() && getVaultKey() !== null;
}

function cacheVaultKey(vk) {
  localStorage.setItem(VK_KEY, crypto.toHex(vk));
  localStorage.setItem(ENABLED_KEY, 'true');
}

// Forget the key on this device (stays enabled; sync pauses until unlocked).
export function lock() {
  localStorage.removeItem(VK_KEY);
}

// ── vault.json in the shared folder ──────────────────────────────────
export async function vaultExists(transport) {
  return (await transport.get(VAULT_FILENAME)) != null;
}

async function loadVault(transport) {
  const text = await transport.get(VAULT_FILENAME);
  if (!text) return null;
  try {
    return JSON.parse(text);
  } catch {
    return null;
  }
}

// ── lifecycle ────────────────────────────────────────────────────────
export async function enableEncryption(transport, passphrase) {
  await crypto.ready;
  if (await vaultExists(transport)) {
    throw new Error('a vault already exists — unlock it instead');
  }
  const { vault, vaultKey, recoveryKey } = crypto.createVault(passphrase);
  await transport.put(VAULT_FILENAME, JSON.stringify(vault));
  cacheVaultKey(vaultKey);
  return { recoveryKey, vaultKey };
}

export async function unlockWithPassphrase(transport, passphrase) {
  await crypto.ready;
  const vault = await loadVault(transport);
  if (!vault) throw new Error('no vault.json in the cloud folder');
  const vk = crypto.unwrapWithPassphrase(vault, passphrase);
  cacheVaultKey(vk);
  return vk;
}

export async function unlockWithRecovery(transport, recoveryKey) {
  await crypto.ready;
  const vault = await loadVault(transport);
  if (!vault) throw new Error('no vault.json in the cloud folder');
  const vk = crypto.unwrapWithRecovery(vault, recoveryKey);
  cacheVaultKey(vk);
  return vk;
}

export async function status(transport) {
  return {
    enabled: isEncryptionEnabled(),
    unlocked: isUnlocked(),
    vaultInFolder: await vaultExists(transport)
  };
}

// ── Device pairing: VK hand-off without the passphrase ───────────────
// Twin of app/sync_vault.py's pairing block. The Vault Key is rendered in
// the same grouped base32 the recovery key uses; the QR payload wraps it
// in a versioned prefix. Scanning/typing the code replaces typing the
// passphrase on the second device.

export const PAIRING_PREFIX = 'indexlife-pair:v1:';

// The code to DISPLAY on this device (phone → PC direction). Null while
// locked — nothing to hand off.
export function getPairingCode() {
  const vk = getVaultKey();
  return vk ? crypto.encodeRecoveryKey(vk) : null;
}

export function getPairingPayload() {
  const code = getPairingCode();
  return code ? PAIRING_PREFIX + code : null;
}

// Accept a scanned QR payload or a hand-typed grouped code; cache the key
// and enable encryption. Throws when the text isn't a 32-byte key.
//
// When a transport is given, the key is VERIFIED against the folder first —
// the mirror of the desktop's adopt_pairing_code: if any peer envelope
// exists, it must decrypt with the pasted key. Without this, scanning a
// code while connected to the wrong cloud/account "unlocked" happily and
// then silently never received the desktop's entries.
export async function adoptPairingCode(text, transport = null) {
  await crypto.ready;
  let cleaned = (text || '').trim();
  if (cleaned.toLowerCase().startsWith(PAIRING_PREFIX)) {
    cleaned = cleaned.slice(PAIRING_PREFIX.length);
  }
  const vk = crypto.decodeRecoveryKey(cleaned);
  if (vk.length !== crypto.VK_BYTES) {
    throw new Error('Код не распознан — проверьте, что он скопирован целиком');
  }
  if (transport) {
    let names = [];
    try {
      names = await transport.list();
    } catch {
      /* folder unreachable — adopt unverified; the devices panel will tell */
    }
    for (const name of names) {
      if (!name.startsWith('device_') || !name.endsWith('.json')) continue;
      const blob = await transport.get(name);
      if (!blob) continue;
      let obj;
      try {
        obj = JSON.parse(blob);
      } catch {
        continue;
      }
      if (!isEnvelope(obj)) continue;
      try {
        crypto.openEnvelope(blob, vk);
      } catch {
        throw new Error(
          'Код не подходит к данным этого облака — проверьте, что выбраны ' +
          'то же облако и тот же аккаунт, что на компьютере'
        );
      }
      break; // first envelope decrypted — the key is verified
    }
  }
  cacheVaultKey(vk);
  return vk;
}

// ── Device display name ──────────────────────────────────────────────
// Shown in peers' device panels instead of a bare uuid. Travels inside the
// (encrypted) snapshot body — envelope headers stay name-free (AAD).

const NAME_KEY = 'indexlife:device-name';

export function getDeviceName() {
  return localStorage.getItem(NAME_KEY) || 'Телефон';
}

export function setDeviceName(name) {
  const clean = (name || '').trim().slice(0, 60);
  if (clean) localStorage.setItem(NAME_KEY, clean);
  else localStorage.removeItem(NAME_KEY);
}
